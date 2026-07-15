"""Single-entrypoint CLI: `clipscore <subcommand>`.

Wired via [project.scripts] in pyproject (clipscore = "clipscore.cli:main"), so
after `pip install -e .` these are real terminal commands:

    clipscore setup     # create tables + load seeds (platform_trust, niche_baselines)
    clipscore poll      # one ingest+score cycle against the configured DB
    clipscore rank [--top N] [--niche X]
    clipscore smoke [db_path]   # live capture check into a throwaway DB
    clipscore bot       # run the Discord bot (needs CLIPSCORE_DISCORD_TOKEN)
    clipscore extract   # one incremental Pipeline B enrich_batch sweep (only_stale)
    clipscore extract --report   # OPERATOR-RUN: full coverage spike report (needs LLM key)
    clipscore clip <campaign_id> [--source-type T] [--source-ref R]   # queue a clip-factory job

The configured DB is CLIPSCORE_DB_URL (see config.Settings). `setup` uses the ORM
metadata directly; production schema upgrades still go through `alembic upgrade head`.
"""
import argparse

from clipscore.config import get_settings
from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401  register ORM tables on Base.metadata
from clipscore.db.session import get_engine, SessionLocal
from clipscore.seed import seed_all
from clipscore.jobs.poll import run_once
from clipscore.jobs.rank import ranked_rows, format_table
from clipscore.jobs.smoke import run_smoke
from clipscore.bot.discord_bot import run_bot
from clipscore.factory.enrich import enrich_batch
from clipscore.factory.report import generate_coverage_spike_report
from clipscore.jobs.clipfactory import create_clip_job


def _setup(args) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_all(s)
    print("setup complete: tables ensured + platform_trust/niche_baselines seeded")


def _poll(args) -> None:
    get_engine()  # binds SessionLocal to the configured engine (side effect)
    with SessionLocal() as s:
        print(run_once(s))


def _rank(args) -> None:
    get_engine()
    with SessionLocal() as s:
        print(format_table(ranked_rows(s, top=args.top, niche=args.niche)))


def _smoke(args) -> None:
    run_smoke(args.db)


def _bot(args) -> None:
    get_engine()
    run_bot(SessionLocal)


def _extract(args) -> None:
    get_engine()
    with SessionLocal() as s:
        settings = get_settings()
        if args.report:
            content = generate_coverage_spike_report(s, settings)
            print(f"wrote coverage spike report ({len(content)} chars)")
        else:
            print(enrich_batch(s, settings, only_stale=True))


def _clip(args) -> None:
    get_engine()
    with SessionLocal() as s:
        settings = get_settings()
        try:
            job = create_clip_job(
                s, args.campaign_id, settings,
                source_type=args.source_type, source_ref=args.source_ref,
            )
        except ValueError as exc:
            print(f"could not queue clip job: {exc}")
            return
        print(f"queued clip job {job.id} (status={job.status})")


def _web(args) -> None:
    import uvicorn
    from clipscore.web.app import create_app
    uvicorn.run(create_app(get_settings()), host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipscore", description="clipscore pipeline commands")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="create tables + load seeds").set_defaults(fn=_setup)
    sub.add_parser("poll", help="run one ingest+score cycle").set_defaults(fn=_poll)

    rp = sub.add_parser("rank", help="print the within-niche screening board")
    rp.add_argument("--top", type=int, default=10)
    rp.add_argument("--niche", default=None)
    rp.set_defaults(fn=_rank)

    sp = sub.add_parser("smoke", help="live capture smoke test (throwaway DB)")
    sp.add_argument("db", nargs="?", default="smoke_clipscore.db", help="sqlite path")
    sp.set_defaults(fn=_smoke)

    sub.add_parser("bot", help="run the Discord bot").set_defaults(fn=_bot)

    xp = sub.add_parser("extract", help="incremental Pipeline B enrich_batch sweep")
    xp.add_argument("--report", action="store_true",
                     help="OPERATOR-RUN: full coverage spike report (needs LLM key)")
    xp.set_defaults(fn=_extract)

    cp = sub.add_parser("clip", help="queue a clip-factory job for a campaign")
    cp.add_argument("campaign_id")
    cp.add_argument("--source-type", dest="source_type", default=None)
    cp.add_argument("--source-ref", dest="source_ref", default=None)
    cp.set_defaults(fn=_clip)

    wp = sub.add_parser("web", help="run the local review dashboard")
    wp.add_argument("--host", default="127.0.0.1")
    wp.add_argument("--port", type=int, default=8000)
    wp.set_defaults(fn=_web)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
