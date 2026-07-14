import pytest
from sqlalchemy.exc import IntegrityError
from clipscore.config import get_settings
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.detect import SourceHalted
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.ingest import upsert as upsert_mod
from clipscore.ingest.upsert import run_ingest_batch, upsert_campaign
from clipscore.db.models import Campaign, FetchEvent
from sqlalchemy import select

@pytest.fixture(autouse=True)
def _clear():
    get_settings.cache_clear(); yield; get_settings.cache_clear()

class HaltIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        raise SourceHalted("https://x/discover", "blocked_403", 403, "Forbidden")
    def normalize(self, raw):
        raise AssertionError("should not be called")

class MostlyGoodIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        return [{"ok": True, "eid": str(i)} for i in range(60)] + [{"bad": True}]
    def normalize(self, raw):
        if raw.get("bad"):
            raise ValueError("malformed entry")
        return CampaignUpsert(source="cr", external_id=raw["eid"], status="active",
                              snapshot=SnapshotData(budget_total_usd=100, budget_remaining_usd=50))

def test_halt_logs_and_flips_no_sweep(session):
    res = run_ingest_batch(session, HaltIngester())
    assert res["status"] == "halted" and res["event_type"] == "blocked_403"
    assert session.execute(select(FetchEvent)).scalars().one().event_type == "blocked_403"


class TransientErrorIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        raise SourceHalted("https://x/discover", "error", 500, "Internal Server Error")
    def normalize(self, raw):
        raise AssertionError("should not be called")


class EmptyParseIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        raise SourceHalted("https://x/discover", "empty_parse", 200, "body too short")
    def normalize(self, raw):
        raise AssertionError("should not be called")


@pytest.mark.parametrize("ingester_cls, event_type", [
    (TransientErrorIngester, "error"),
    (EmptyParseIngester, "empty_parse"),
])
def test_transient_fetch_failure_logs_but_does_not_flip_access_status(session, ingester_cls, event_type):
    existing = CampaignUpsert(source="cr", external_id="preexisting", status="active",
                              snapshot=SnapshotData(budget_total_usd=100, budget_remaining_usd=50))
    upsert_campaign(session, existing, "2026-07-13T00:00:00Z")

    res = run_ingest_batch(session, ingester_cls())

    assert res["status"] == "fetch_failed"
    assert res["event_type"] == event_type
    assert session.execute(select(FetchEvent)).scalars().one().event_type == event_type
    campaign = session.execute(
        select(Campaign).where(Campaign.external_id == "preexisting")
    ).scalars().one()
    assert campaign.access_status == "ingestable"
    assert campaign.status == "active"

def test_malformed_entry_skipped(session):
    res = run_ingest_batch(session, MostlyGoodIngester())
    assert res["status"] == "ok" and res["count"] == 61 and res["skipped"] == 1
    assert len(session.execute(select(Campaign)).scalars().all()) == 60


class GoodIngester(BaseIngester):
    """All entries normalize fine; used to isolate a DB-time (not normalize-time) failure."""
    source_name = "cr"
    def __init__(self, n):
        self._n = n
    def fetch(self):
        return [{"eid": str(i)} for i in range(self._n)]
    def normalize(self, raw):
        return CampaignUpsert(source="cr", external_id=raw["eid"], status="active",
                              snapshot=SnapshotData(budget_total_usd=100, budget_remaining_usd=50))


def test_db_time_failure_mid_batch_rolls_back_and_does_not_cascade(session, monkeypatch):
    # 55 raws, all normalize cleanly. One specific external_id fails INSIDE
    # upsert_campaign (a DB-time error, e.g. IntegrityError), which leaves the
    # SQLAlchemy 2.0 session pending-rollback unless we roll back explicitly.
    poison_id = "30"
    real_upsert_campaign = upsert_campaign

    def flaky_upsert_campaign(session, up, seen_at):
        if up.external_id == poison_id:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return real_upsert_campaign(session, up, seen_at)

    monkeypatch.setattr(upsert_mod, "upsert_campaign", flaky_upsert_campaign)

    rollback_calls = []
    orig_rollback = session.rollback

    def spy_rollback():
        rollback_calls.append(1)
        return orig_rollback()

    monkeypatch.setattr(session, "rollback", spy_rollback)

    res = run_ingest_batch(session, GoodIngester(55))

    assert res["status"] == "ok"
    assert res["count"] == 55
    assert res["skipped"] == 1
    assert rollback_calls == [1]
    # every entry after the poisoned one must still have persisted (no cascade)
    persisted_ids = {c.external_id for c in session.execute(select(Campaign)).scalars().all()}
    assert persisted_ids == {str(i) for i in range(55) if str(i) != poison_id}


class AllBadNormalizeIngester(BaseIngester):
    """A systemic normalize break (e.g. source renames `id`): passes the raw-count
    gate but produces zero valid campaigns."""
    source_name = "cr"
    def __init__(self, n):
        self._n = n
    def fetch(self):
        return [{"nope": True} for _ in range(self._n)]
    def normalize(self, raw):
        raise KeyError("id")


def test_all_normalize_failures_skip_sweep_and_preserve_active_campaign(session):
    get_settings.cache_clear()
    settings = get_settings()
    min_campaigns = settings.harvest_min_campaigns

    # pre-existing active campaign that a runaway sweep would otherwise end
    existing = CampaignUpsert(source="cr", external_id="preexisting", status="active",
                              snapshot=SnapshotData(budget_total_usd=100, budget_remaining_usd=50))
    upsert_campaign(session, existing, "2026-07-13T00:00:00Z")

    ingester = AllBadNormalizeIngester(min_campaigns)
    res = run_ingest_batch(session, ingester)

    assert res["status"] == "ok"
    assert res["ended"] == 0
    assert res.get("sweep_skipped") is True
    assert res["skipped"] == min_campaigns
    assert session.execute(
        select(Campaign).where(Campaign.external_id == "preexisting")
    ).scalars().one().status == "active"
