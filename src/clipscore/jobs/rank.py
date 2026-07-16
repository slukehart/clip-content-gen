"""CLI: python -m clipscore.jobs.rank --top N [--niche X]
Within-niche screening board. cvs_niche_percentile is the signal; cvs_raw is an
internal scalar shown for debugging, NEVER a $/hr promise."""
import argparse
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.scoring.board import eligible_latest_scores
from clipscore.db.session import get_engine, SessionLocal

CAVEAT = "estimated screening signal, not a payout prediction"


def ranked_rows(session: Session, top: int | None = None, niche: str | None = None,
                niches: frozenset[str] | set[str] | None = None) -> list[dict]:
    """`niche` (singular, exact match) is the legacy per-call override.
    `niches` is the configured lane -- a set of lowercased niche names; when
    non-empty, only campaigns whose niche is in the set are kept. An empty/None
    `niches` applies no lane filter."""
    rows = []
    for c, s in eligible_latest_scores(session):
        key = c.niche or "other"
        if niche is not None and key != niche:
            continue
        if niches and key.lower() not in niches:
            continue
        rows.append(dict(campaign_id=s.campaign_id, title=c.title, niche=key,
                         cpm_usd=c.cpm_usd, net_cpm=s.net_cpm,
                         budget_health=s.budget_health, sat_factor=s.sat_factor,
                         cvs_raw=s.cvs_raw, cvs_niche_percentile=s.cvs_niche_percentile))
    rows.sort(key=lambda r: (r["cvs_niche_percentile"] is not None,
                             r["cvs_niche_percentile"] or 0.0), reverse=True)
    return rows[:top] if top else rows


def _fmt(v, spec="{:.3f}"):
    return "-" if v is None else spec.format(v)


def format_table(rows: list[dict]) -> str:
    header = f"{'#':>3}  {'niche':<16} {'title':<28} {'cpm':>6} {'net':>6} " \
             f"{'bhlth':>6} {'sat':>6} {'cvs_raw':>8} {'pctile':>7}"
    lines = [f"Campaign screening board — {CAVEAT}.", "", header, "-" * len(header)]
    for i, r in enumerate(rows, 1):
        title = (r["title"] or "")[:28]
        lines.append(
            f"{i:>3}  {r['niche']:<16} {title:<28} "
            f"{_fmt(r['cpm_usd'], '{:.2f}'):>6} {_fmt(r['net_cpm'], '{:.2f}'):>6} "
            f"{_fmt(r['budget_health'], '{:.2f}'):>6} {_fmt(r['sat_factor'], '{:.2f}'):>6} "
            f"{_fmt(r['cvs_raw']):>8} {_fmt(r['cvs_niche_percentile'], '{:.2f}'):>7}"
        )
    if not rows:
        lines.append("(no scored campaigns)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="clipscore.jobs.rank")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--niche", type=str, default=None)
    args = ap.parse_args(argv)
    get_engine()
    niches = None if args.niche else get_settings().target_niche_set
    with SessionLocal() as session:
        print(format_table(ranked_rows(session, top=args.top, niche=args.niche, niches=niches)))


if __name__ == "__main__":
    main()
