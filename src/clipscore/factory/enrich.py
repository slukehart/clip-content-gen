"""Guarded orchestration tying the deterministic floor (`extract.py`) to the
optional Whop-page fetch (`whop.py`) and LLM adapter (`extract_llm.py`).

This is the one rule that matters here: extraction can NEVER break Pipeline
A. `enrich_campaign` always produces a result and never raises -- any
failure (no API key, LLM error, blocked/challenged fetch, or anything else
unexpected) falls back to the regex floor. `enrich_batch` is the poll-time /
report-time sweep over clipping campaigns.
"""
import json
import time
import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign
from clipscore.factory.extract import (
    ExtractedTargets,
    RegexExtractor,
    apply_to_campaign,
    compute_input_hash,
    merge_extractions,
)
from clipscore.factory.whop import fetch_page_text

log = structlog.get_logger()

_CLIPPING_TYPES = ("clipping", "both")


def _platforms(raw) -> list[str]:
    """`Campaign.allowed_socials` is a JSON column and is normally a list, but
    may arrive as a JSON-encoded string (e.g. from hand-built test fixtures
    or older rows) -- normalize either shape to a plain list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return val if isinstance(val, list) else []
    return []


def _regex_floor(campaign: Campaign, page_text: str | None) -> ExtractedTargets:
    base_platforms = _platforms(campaign.allowed_socials)
    return RegexExtractor().extract(campaign.requirements_raw, page_text, base_platforms)


def _enrich_campaign_inner(session: Session, campaign: Campaign, settings: Settings,
                           extractor, fetch) -> ExtractedTargets:
    base_platforms = _platforms(campaign.allowed_socials)
    description = campaign.requirements_raw

    page_text = None
    if settings.extract_from_whop_page and campaign.url:
        try:
            fetch_fn = fetch or fetch_page_text
            page_text = fetch_fn(campaign.url)
        except Exception:
            log.warning("enrich_fetch_failed", campaign_id=campaign.id, url=campaign.url)
            page_text = None

    regex_result = RegexExtractor().extract(description, page_text, base_platforms)

    llm_result = ExtractedTargets()
    # `extractor` is a DI seam for tests (a fake LLM); production code only
    # attempts the real LLMExtractor when a key is configured.
    if settings.extract_from_whop_page and (extractor is not None or settings.llm_api_key):
        try:
            llm = extractor if extractor is not None else _default_llm_extractor(settings)
            llm_result = llm.extract(description, page_text, base_platforms)
        except Exception:
            log.warning("enrich_llm_failed", campaign_id=campaign.id)
            llm_result = ExtractedTargets()

    merged = merge_extractions(regex_result, llm_result, base_platforms)
    apply_to_campaign(campaign, merged)
    session.commit()
    return merged


def _default_llm_extractor(settings: Settings):
    from clipscore.factory.extract_llm import LLMExtractor
    return LLMExtractor(settings)


def enrich_campaign(session: Session, campaign: Campaign, settings: Settings,
                    extractor=None, fetch=None) -> ExtractedTargets:
    """Run the regex floor, and (if configured) layer an LLM pass on top,
    merge, apply to `campaign`, and commit. Never raises -- on any internal
    failure it falls back to the regex-only result, and as a last resort to
    an empty (all-absent) result, rather than letting an extraction problem
    propagate into Pipeline A's ingest/scoring path."""
    if not settings.extract_enabled:
        return ExtractedTargets()

    try:
        return _enrich_campaign_inner(session, campaign, settings, extractor, fetch)
    except Exception:
        log.error("enrich_campaign_failed_hard", campaign_id=getattr(campaign, "id", None))
        try:
            session.rollback()
            regex_result = _regex_floor(campaign, None)
            apply_to_campaign(campaign, regex_result)
            session.commit()
            return regex_result
        except Exception:
            log.error("enrich_campaign_regex_floor_also_failed",
                      campaign_id=getattr(campaign, "id", None))
            return ExtractedTargets()


def _is_stale(campaign: Campaign) -> bool:
    """Does this campaign need (re-)extraction?

    - Never extracted (`extract_provenance IS NULL`) -> stale.
    - Extracted, with a stored input hash that no longer matches a freshly
      computed one (its `requirements_raw` changed, or `EXTRACT_VERSION` was
      bumped) -> stale.
    - Legacy row extracted before the hash column existed (provenance set but
      `extract_input_hash IS NULL`) -> NOT stale: grandfathered so deploying
      this change doesn't trigger a one-time re-extraction of every campaign.
      No poll/CLI path re-extracts these, so they stay grandfathered
      permanently; the only way to opt one back in is a deliberate full
      (`only_stale=False`) sweep, which nothing wires today. Acceptable: this
      matters only for rows extracted by an earlier build, and the cost guard
      (plan: "Never re-extract all ~405") is why we don't do it automatically.
    """
    if campaign.extract_provenance is None:
        return True
    if campaign.extract_input_hash is None:
        return False
    return campaign.extract_input_hash != compute_input_hash(campaign.requirements_raw)


def enrich_batch(session: Session, settings: Settings, only_stale: bool = True,
                 extractor=None, fetch=None) -> dict:
    """Sweep clipping/both campaigns and enrich each one.

    `only_stale=True` (the poll path) loads all clipping/both campaigns and
    keeps the ones `_is_stale` flags -- never-extracted, or whose extraction
    input changed since the last pass (see `_is_stale`). Filtering in Python
    rather than SQL is cheap: the hash covers short text, and the expensive
    fetch+LLM still only runs on the stale campaigns. `only_stale=False`
    re-extracts every clipping/both campaign unconditionally (stamping a hash
    on each, including legacy rows) -- it exists for a deliberate full
    re-extraction, but no poll/CLI path invokes it today.
    """
    if not settings.extract_enabled:
        return {"processed": 0, "skipped": "extract_disabled"}

    query = select(Campaign).where(Campaign.campaign_type.in_(_CLIPPING_TYPES))
    campaigns = session.execute(query).scalars().all()
    if only_stale:
        campaigns = [c for c in campaigns if _is_stale(c)]
    processed = 0

    if fetch is not None:
        # Tests (and any other caller) inject their own `fetch` -- no real
        # network happens here, so no shared client/robots-cache/pacing is
        # needed and CI stays fast.
        for campaign in campaigns:
            enrich_campaign(session, campaign, settings, extractor=extractor, fetch=fetch)
            processed += 1
        return {"processed": processed}

    # Real network sweep: share ONE httpx.Client and ONE per-run robots.txt
    # verdict cache across every campaign in this batch (robots.txt fetched
    # at most once per host, not once per campaign -- see
    # plans/pipeline-b-stage-1-extraction.md Global Constraints), and apply a
    # small configurable pacing delay between real page fetches.
    robots_cache: dict = {}
    with httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True) as client:
        def _paced_fetch(url: str) -> str | None:
            text = fetch_page_text(url, client=client, robots_cache=robots_cache)
            time.sleep(settings.whop_fetch_pacing_s)
            return text

        for campaign in campaigns:
            enrich_campaign(session, campaign, settings, extractor=extractor, fetch=_paced_fetch)
            processed += 1

    return {"processed": processed}
