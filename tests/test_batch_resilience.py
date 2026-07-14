import pytest
from clipscore.config import get_settings
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.detect import SourceHalted
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.ingest.upsert import run_ingest_batch
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

def test_malformed_entry_skipped(session):
    res = run_ingest_batch(session, MostlyGoodIngester())
    assert res["status"] == "ok" and res["count"] == 61 and res["skipped"] == 1
    assert len(session.execute(select(Campaign)).scalars().all()) == 60
