"""Manual, operator-run coverage calibration report: regex-floor vs LLM-ceiling
vs +Whop-page-delta over a stratified sample of real clipping/both campaigns.

OPERATOR-RUN ONLY -- needs a live LLM key (`settings.llm_api_key`) and network
access (the Whop page fetch). Never invoked in CI; only `stratify_sample`
(pure) and `coverage_report` (see `factory/coverage.py`) are unit-tested.
`generate_coverage_spike_report` is exercised by `clipscore extract --report`.
"""
import json
from collections import defaultdict

import structlog
from sqlalchemy import select

from clipscore.config import Settings
from clipscore.db.models import Campaign
from clipscore.factory.coverage import coverage_report
from clipscore.factory.extract import RegexExtractor, ExtractedTargets, merge_extractions, FIELDS
from clipscore.factory.extract_llm import LLMExtractor
from clipscore.factory.whop import fetch_page_text

log = structlog.get_logger()

_CLIPPING_TYPES = ("clipping", "both")
_PER_BUCKET = 3
_DEFAULT_OUT_PATH = "docs/spikes/2026-07-14-clip-source-coverage-spike.md"


def _length_bucket(description: str | None) -> str:
    n = len(description or "")
    if n < 200:
        return "short"
    if n < 600:
        return "medium"
    return "long"


def stratify_sample(campaigns, per_bucket: int = _PER_BUCKET) -> list:
    """Pure: group campaigns by (niche, description-length bucket) and take up
    to `per_bucket` from each group, preserving input order within a group."""
    buckets: dict[tuple, list] = defaultdict(list)
    for c in campaigns:
        key = (getattr(c, "niche", None), _length_bucket(getattr(c, "requirements_raw", None)))
        buckets[key].append(c)
    sample = []
    for key in sorted(buckets, key=lambda k: (k[0] or "", k[1])):
        sample.extend(buckets[key][:per_bucket])
    return sample


def _platforms(raw) -> list[str]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return val if isinstance(val, list) else []
    return []


def _row_from(extracted: ExtractedTargets) -> dict:
    return {
        "content_bank_url": extracted.content_bank_url,
        "target_creator": extracted.target_creator,
        "target_platforms": extracted.target_platforms,
        "clip_min_len_s": extracted.clip_min_len_s,
        "clip_max_len_s": extracted.clip_max_len_s,
        "caption_rules": extracted.caption_rules,
        "banned_content": extracted.banned_content,
        "extract_provenance": extracted.provenance,
    }


def _format_table(report: dict) -> str:
    lines = [f"total sampled: {report['total']}", "", "| field | coverage % |", "|---|---|"]
    for f in FIELDS:
        lines.append(f"| {f} | {report['field_coverage_pct'][f]} |")
    lines.append("")
    lines.append("footage-source distribution:")
    for k, v in report["footage_source_distribution"].items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def generate_coverage_spike_report(session, settings: Settings,
                                   out_path: str = _DEFAULT_OUT_PATH) -> str:
    """OPERATOR-RUN: needs `settings.llm_api_key` + network. Samples
    clipping/both campaigns (stratified by niche + description-length
    bucket), computes regex-floor / LLM-ceiling (no page fetch) /
    +Whop-page-delta extraction results for each, writes a Phase-0-spike-
    style markdown report to `out_path`, and returns its content."""
    if not settings.llm_api_key:
        raise RuntimeError("generate_coverage_spike_report requires settings.llm_api_key")

    campaigns = session.execute(
        select(Campaign).where(Campaign.campaign_type.in_(_CLIPPING_TYPES))
    ).scalars().all()
    sample = stratify_sample(campaigns)
    log.info("coverage_spike_sample", total_campaigns=len(campaigns), sampled=len(sample))

    llm = LLMExtractor(settings)
    regex = RegexExtractor()

    floor_rows, ceiling_rows, whop_rows = [], [], []
    for c in sample:
        base_platforms = _platforms(c.allowed_socials)
        description = c.requirements_raw

        floor = regex.extract(description, None, base_platforms)
        floor_rows.append(_row_from(floor))

        try:
            llm_no_page = llm.extract(description, None, base_platforms)
        except Exception:
            log.warning("coverage_spike_llm_failed", campaign_id=c.id)
            llm_no_page = ExtractedTargets()
        ceiling = merge_extractions(floor, llm_no_page, base_platforms)
        ceiling_rows.append(_row_from(ceiling))

        page_text = fetch_page_text(c.url) if c.url else None
        floor_with_page = regex.extract(description, page_text, base_platforms)
        try:
            llm_with_page = llm.extract(description, page_text, base_platforms) if page_text else llm_no_page
        except Exception:
            log.warning("coverage_spike_llm_whop_failed", campaign_id=c.id)
            llm_with_page = llm_no_page
        whop = merge_extractions(floor_with_page, llm_with_page, base_platforms)
        whop_rows.append(_row_from(whop))

    floor_report = coverage_report(floor_rows)
    ceiling_report = coverage_report(ceiling_rows)
    whop_report = coverage_report(whop_rows)

    md = [
        "# Clip-source coverage spike -- 2026-07-14",
        "",
        f"Stratified sample: {len(sample)} campaigns (of {len(campaigns)} clipping/both) "
        "by niche + description-length bucket (short/medium/long).",
        "",
        "## Regex floor (description-only, no LLM, no Whop page)",
        "",
        _format_table(floor_report),
        "",
        "## LLM ceiling (description only, no Whop page fetch)",
        "",
        _format_table(ceiling_report),
        "",
        "## +Whop-page delta (description + fetched Whop product page)",
        "",
        _format_table(whop_report),
        "",
        "## Footage-source distribution (final, +Whop)",
        "",
        *(f"- {k}: {v}" for k, v in whop_report["footage_source_distribution"].items()),
        "",
    ]
    content = "\n".join(md)

    with open(out_path, "w") as f:
        f.write(content)
    log.info("coverage_spike_written", path=out_path)
    return content
