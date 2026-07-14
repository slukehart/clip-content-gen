"""Single-entrypoint CLI: `clipscore <subcommand>`.

Wired via [project.scripts] in pyproject (clipscore = "clipscore.cli:main"), so
after `pip install -e .` these are real terminal commands:

    clipscore setup     # create tables + load seeds (platform_trust, niche_baselines)
    clipscore poll      # one ingest+score cycle against the configured DB
    clipscore rank [--top N] [--niche X]
    clipscore smoke [db_path]   # live capture check into a throwaway DB
    clipscore bot       # run the Discord bot (needs CLIPSCORE_DISCORD_TOKEN)

The configured DB is CLIPSCORE_DB_URL (see config.Settings). `setup` uses the ORM
metadata directly; production schema upgrades still go through `alembic upgrade head`.
"""
import argparse

from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401  register ORM tables on Base.metadata
from clipscore.db.session import get_engine, SessionLocal
from clipscore.seed import seed_all
from clipscore.jobs.poll import run_once
from clipscore.jobs.rank import ranked_rows, format_table
from clipscore.jobs.smoke import run_smoke
from clipscore.bot.discord_bot import run_bot


def _setup(args) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_all(s)
    print("setup complete: tables ensured + platform_trust/niche_baselines seeded")


def _poll(args) -> None:
    get_engine()
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
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
