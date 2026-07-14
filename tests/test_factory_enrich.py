import json
import uuid
import httpx
from clipscore.db.models import Campaign
from clipscore.factory.extract import ExtractedTargets
from clipscore.factory import enrich
from clipscore.config import Settings
from clipscore.time import utcnow_iso

_PAGE = "<html>" + "self.__next_f.push(['x','product data here'])" + " " * 1200 + "</html>"


class FakeExtractor:
    def __init__(self, result):
        self._result = result

    def extract(self, description, page_text, base_platforms):
        return self._result


def _campaign(**kw):
    now = utcnow_iso()
    defaults = dict(
        id=uuid.uuid4().hex,
        source="cr", external_id="x", url="https://whop.com/x",
        status="active", campaign_type="clipping",
        requirements_raw="Clip @diego. Footage https://drive.google.com/f/1",
        allowed_socials=["tiktok"],
        first_seen_at=now, last_seen_at=now,
    )
    defaults.update(kw)
    return Campaign(**defaults)


def test_llm_result_merges_onto_campaign_with_whop_page_provenance(session):
    c = _campaign()
    session.add(c)
    session.commit()
    llm_result = ExtractedTargets(
        clip_min_len_s=15, clip_max_len_s=60, caption_rules="no profanity",
        provenance={"clip_min_len_s": "whop_page", "clip_max_len_s": "whop_page",
                    "caption_rules": "whop_page"},
    )
    res = enrich.enrich_campaign(
        session, c, Settings(_env_file=None),
        extractor=FakeExtractor(llm_result), fetch=lambda *a, **k: "page text",
    )
    assert c.clip_min_len_s == 15
    assert c.clip_max_len_s == 60
    assert c.caption_rules == "no profanity"
    prov = json.loads(c.extract_provenance)
    assert prov["clip_min_len_s"] == "whop_page"
    # regex floor is still present alongside the LLM-sourced fields
    assert c.content_bank_url == "https://drive.google.com/f/1"
    assert res is not None


def test_llm_failure_falls_back_to_regex_and_never_raises(session, monkeypatch):
    now = utcnow_iso()
    c = Campaign(id=uuid.uuid4().hex, source="cr", external_id="x", url="https://whop.com/x",
                 status="active", campaign_type="clipping",
                 requirements_raw="Clip @diego. Footage https://drive.google.com/f/1",
                 allowed_socials='["tiktok"]', first_seen_at=now, last_seen_at=now)
    session.add(c)
    session.commit()

    class Boom:
        def extract(self, *a, **k):
            raise RuntimeError("llm down")

    res = enrich.enrich_campaign(session, c, Settings(_env_file=None),
                                 extractor=Boom(), fetch=lambda *a, **k: "page text")
    assert c.content_bank_url == "https://drive.google.com/f/1"  # regex floor survived
    assert res is not None                                        # did not raise


def test_blocked_fetch_still_falls_back_to_regex(session):
    c = _campaign()
    session.add(c)
    session.commit()

    res = enrich.enrich_campaign(session, c, Settings(_env_file=None),
                                 extractor=FakeExtractor(ExtractedTargets()),
                                 fetch=lambda *a, **k: None)  # drop-don't-evade: blocked fetch
    assert c.content_bank_url == "https://drive.google.com/f/1"
    assert res is not None


def test_no_key_no_extractor_skips_llm_and_uses_regex_only(session):
    c = _campaign()
    session.add(c)
    session.commit()

    res = enrich.enrich_campaign(session, c, Settings(_env_file=None),
                                 fetch=lambda *a, **k: "page text")
    assert c.content_bank_url == "https://drive.google.com/f/1"
    assert res is not None


def test_extract_disabled_is_noop(session):
    c = _campaign()
    session.add(c)
    session.commit()

    res = enrich.enrich_campaign(
        session, c, Settings(_env_file=None, extract_enabled=False),
        extractor=FakeExtractor(ExtractedTargets(content_bank_url="https://drive.google.com/should-not-apply")),
        fetch=lambda *a, **k: "page text",
    )
    assert c.content_bank_url is None
    assert c.extract_provenance is None
    assert res is not None


def test_enrich_batch_only_stale_skips_already_extracted(session):
    c1 = _campaign(external_id="a")
    c1.extract_provenance = json.dumps({"content_bank_url": "absent"})
    c2 = _campaign(external_id="b")
    session.add_all([c1, c2])
    session.commit()

    result = enrich.enrich_batch(session, Settings(_env_file=None), only_stale=True,
                                 fetch=lambda *a, **k: None)
    assert result["processed"] == 1
    assert c2.extract_provenance is not None


def test_enrich_batch_skips_non_clipping_campaigns(session):
    c = _campaign(campaign_type="deal_finder_only")
    session.add(c)
    session.commit()

    result = enrich.enrich_batch(session, Settings(_env_file=None), only_stale=True,
                                 fetch=lambda *a, **k: None)
    assert result["processed"] == 0


def test_enrich_batch_real_sweep_caches_robots_and_shares_client(session, monkeypatch):
    """Compliance fix: within one enrich_batch call over several campaigns on
    the real (non-injected-fetch) network path, robots.txt must be fetched at
    MOST ONCE per host, and a single httpx.Client + a sleep-per-page-fetch
    pacing must be used -- not one client/robots-check per campaign."""
    c1 = _campaign(external_id="a", url="https://whop.com/a")
    c2 = _campaign(external_id="b", url="https://whop.com/b")
    c3 = _campaign(external_id="c", url="https://whop.com/c")
    session.add_all([c1, c2, c3])
    session.commit()

    robots_requests = []
    page_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            robots_requests.append(request.url.host)
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        page_requests.append(request.url.path)
        return httpx.Response(200, text=_PAGE)

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.Client
    client_instances = []

    def fake_client(*args, **kwargs):
        inst = real_client_cls(*args, transport=transport, **kwargs)
        client_instances.append(inst)
        return inst

    monkeypatch.setattr(enrich.httpx, "Client", fake_client)

    sleeps = []
    monkeypatch.setattr(enrich.time, "sleep", lambda s: sleeps.append(s))

    settings = Settings(_env_file=None, whop_fetch_pacing_s=0.01)
    result = enrich.enrich_batch(session, settings, only_stale=True, fetch=None)

    assert result["processed"] == 3
    # robots.txt fetched AT MOST ONCE across the whole sweep, not once per campaign
    assert len(robots_requests) == 1
    assert len(page_requests) == 3
    # exactly one httpx.Client was constructed for the whole sweep
    assert len(client_instances) == 1
    # pacing sleep applied once per real page fetch, using the configured delay
    assert sleeps == [0.01, 0.01, 0.01]


def test_enrich_batch_noop_when_extract_disabled(session):
    c = _campaign()
    session.add(c)
    session.commit()

    result = enrich.enrich_batch(session, Settings(_env_file=None, extract_enabled=False),
                                 only_stale=True, fetch=lambda *a, **k: None)
    assert result["processed"] == 0
    assert c.content_bank_url is None
