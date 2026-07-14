"""Best-effort regex extraction of caps/thresholds from a campaign's free-text
`description` (contentrewards has no structured requirements field). Coverage is
partial by design: no match => provenance 'absent' (NOT 'uncapped')."""
import re
from clipscore.ingest.coerce import money_to_float, views_to_int

_CAP = re.compile(r"(?:max|cap|up to|maximum)\D{0,15}\$\s?([\d,]+(?:\.\d+)?)\s*(?:/\s*|per\s+)(?:video|post|clip)", re.I)
_MIN_VIEWS = re.compile(r"(?:min(?:imum)?(?:\s+floor)?|floor|at least)\D{0,15}?([\d,]+)\s*views", re.I)
_MIN_PAYOUT = re.compile(r"min(?:imum)?\s+payout\D{0,10}\$\s?([\d,]+(?:\.\d+)?)", re.I)

def extract_requirements(description: str | None) -> dict:
    out = {"cap_per_post_usd": None, "cap_provenance": "absent",
           "min_views_threshold": None, "min_payout_threshold_usd": None}
    if not description:
        return out
    m = _CAP.search(description)
    if m:
        out["cap_per_post_usd"] = money_to_float(m.group(1))
        if out["cap_per_post_usd"] is not None:
            out["cap_provenance"] = "observed"
    m = _MIN_VIEWS.search(description)
    if m:
        out["min_views_threshold"] = views_to_int(m.group(1))
    m = _MIN_PAYOUT.search(description)
    if m:
        out["min_payout_threshold_usd"] = money_to_float(m.group(1))
    return out
