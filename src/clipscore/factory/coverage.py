"""Pure counting over extraction results -- no network, no LLM, no DB session.

`coverage_report(rows)` accepts an iterable of *row-like* objects: either
dicts or `Campaign`-like objects exposing (via attribute or key) the seven
extracted fields from `factory.extract.FIELDS` plus `extract_provenance`
(a dict of field -> source, one of `description|whop_page|allowed_socials|absent`).

Rows may be plain dicts (as built by the manual report driver from raw query
results) or ORM `Campaign` instances (where `extract_provenance` is the
JSON-encoded string written by `apply_to_campaign` and `target_creator` /
`target_platforms` are JSON-encoded strings too) -- `_get_field` and
`_get_provenance` normalize both shapes.
"""
import json

from clipscore.factory.extract import FIELDS


def _get(row, field, default=None):
    if isinstance(row, dict):
        return row.get(field, default)
    return getattr(row, field, default)


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _provenance_for(row) -> dict:
    raw = _get(row, "extract_provenance", {}) or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = {}
    return raw


def _is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, str)):
        return len(value) > 0
    return True


def coverage_report(rows) -> dict:
    """Count, over `rows`: per-field non-absent coverage %, a provenance
    breakdown per field (counts per source label), and the footage-source
    distribution (`campaign_provided` / `named_creator` / `none`)."""
    rows = list(rows)
    total = len(rows)

    field_present = {f: 0 for f in FIELDS}
    provenance_breakdown: dict[str, dict[str, int]] = {f: {} for f in FIELDS}
    footage = {"campaign_provided": 0, "named_creator": 0, "none": 0}

    for row in rows:
        prov = _provenance_for(row)
        for field in FIELDS:
            source = prov.get(field, "absent")
            provenance_breakdown[field][source] = provenance_breakdown[field].get(source, 0) + 1
            if source != "absent":
                field_present[field] += 1

        bank_url = _get(row, "content_bank_url")
        creators = _as_list(_get(row, "target_creator", []))
        if _is_present(bank_url):
            footage["campaign_provided"] += 1
        elif _is_present(creators):
            footage["named_creator"] += 1
        else:
            footage["none"] += 1

    field_coverage_pct = {
        f: (round(field_present[f] / total * 100, 1) if total else 0.0) for f in FIELDS
    }

    return {
        "total": total,
        "field_coverage_pct": field_coverage_pct,
        "provenance_breakdown": provenance_breakdown,
        "footage_source_distribution": footage,
    }
