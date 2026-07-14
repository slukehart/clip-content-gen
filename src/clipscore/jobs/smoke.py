"""Live capture smoke test: real ingest against contentrewards.com/discover into a
throwaway DB, then score + print everything needed to eyeball capture correctness.
No Discord token required. Exposed as `clipscore smoke [db_path]`.

This makes ONE live GET (robots-checked, honest UA) — it is the manual-acceptance
tool from the Pipeline-A definition of done, not part of the automated test suite.
"""
from collections import Counter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401  register ORM tables
from clipscore.db.models import Campaign, CampaignSnapshot, FetchEvent
from clipscore.seed import seed_all
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.upsert import run_ingest_batch
from clipscore.scoring.engine import score_all
from clipscore.jobs.rank import ranked_rows, format_table

DEFAULT_DB = "smoke_clipscore.db"


def _hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def run_smoke(db_path: str = DEFAULT_DB) -> dict:
    """Run one live ingest+score cycle against `db_path` and print a capture report.
    Returns the ingest batch result dict."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_all(s)

        _hr("1. LIVE INGEST  (GET https://contentrewards.com/discover)")
        result = run_ingest_batch(s, ContentrewardsIngester(), miss_counts={})
        print("batch result:", result)

        if result.get("status") != "ok":
            _hr("INGEST DID NOT COMPLETE — recent fetch_events (diagnosis)")
            for e in s.execute(select(FetchEvent).order_by(FetchEvent.id.desc()).limit(5)).scalars():
                print(f"  {e.detected_at}  {e.event_type}  http={e.http_status}  {e.url}\n    {e.detail}")
            print("\nA block/challenge here is 'drop, don't evade' working as designed.")
            return result

        _hr("2. SCORING")
        print("score result:", score_all(s))

        campaigns = s.execute(select(Campaign)).scalars().all()
        snaps = s.execute(select(CampaignSnapshot)).scalars().all()

        _hr("3. CAPTURE OVERVIEW")
        print(f"campaigns captured : {len(campaigns)}")
        print(f"snapshots written  : {len(snaps)}")
        print(f"unique campaign ids: {len({c.external_id for c in campaigns})}  (should equal campaigns)")
        print("\nby niche        :", dict(Counter(c.niche for c in campaigns).most_common()))
        print("by campaign_type:", dict(Counter(c.campaign_type for c in campaigns)))
        print("by status       :", dict(Counter(c.status for c in campaigns)))
        print("cap_provenance  :", dict(Counter(c.cap_provenance for c in campaigns)))
        print(f"missing/zero cpm: {sum(1 for c in campaigns if not c.cpm_usd)}")

        _hr("4. SAMPLE OF 8 CAPTURED CAMPAIGNS (eyeball field correctness)")
        for c in campaigns[:8]:
            print(f"\n  title      : {c.title!r}")
            print(f"  brand      : {c.brand!r}")
            print(f"  niche      : {c.niche!r}   type: {c.campaign_type!r}   status: {c.status}")
            print(f"  cpm_usd    : {c.cpm_usd}   budget_total: {c.budget_total_usd}")
            print(f"  cap_per_post: {c.cap_per_post_usd}  ({c.cap_provenance})   "
                  f"min_views: {c.min_views_threshold}  min_payout: {c.min_payout_threshold_usd}")
            print(f"  socials    : {c.allowed_socials}")
            print(f"  url        : {c.url}")

        _hr("5. TOP 10 SCORED (within-niche screening board)")
        print(format_table(ranked_rows(s, top=10)))

        print(f"\n(DB persisted at {db_path} — rerun to confirm dedup + a 2nd snapshot per campaign.)")
        return result


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="clipscore-smoke")
    ap.add_argument("db", nargs="?", default=DEFAULT_DB, help="sqlite path (throwaway)")
    args = ap.parse_args(argv)
    run_smoke(args.db)


if __name__ == "__main__":
    main()
