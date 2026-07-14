"""CLI: python -m clipscore.jobs.rank --top N [--niche X]
Within-niche screening board. cvs_niche_percentile is the signal; cvs_raw is an
internal scalar shown for debugging, NEVER a $/hr promise."""
import argparse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from clipscore.db.models import Campaign, CampaignScore
from clipscore.db.session import get_engine, SessionLocal

CAVEAT = "estimated screening signal, not a payout prediction"


def ranked_rows(session: Session, top: int | None = None, niche: str | None = None) -> list[dict]:
    # latest score per campaign = max(id) per campaign_id
    latest_ids = select(func.max(CampaignScore.id)).group_by(CampaignScore.campaign_id)
    scores = session.execute(
        select(CampaignScore).where(CampaignScore.id.in_(latest_ids))
    ).scalars().all()
    camps = {c.id: c for c in session.execute(select(Campaign)).scalars().all()}
    rows = []
    for s in scores:
        c = camps.get(s.campaign_id)
        if c is None:
            continue
        key = c.niche or "other"
        if niche is not None and key != niche:
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
    with SessionLocal() as session:
        print(format_table(ranked_rows(session, top=args.top, niche=args.niche)))


if __name__ == "__main__":
    main()
