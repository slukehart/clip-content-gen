# clip-content-gen

A personal two-pipeline system for finding the best content-clipping campaigns and turning them into review-ready clips.

Short-form "clipping" campaigns pay creators per verified view, but headline CPM is a misleading signal — real value depends on budget health, payout caps, approval rates, view thresholds, clipper saturation, and payout reliability. This project screens campaigns on those factors, then automates the labor of producing clips, leaving the human to do the final revenue step (posting).

## The two pipelines

- **Pipeline A — Deal Finder** ([`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md))
  Ingests campaigns from a public campaign marketplace, stores time-series snapshots, and computes a **Campaign Value Score (CVS)** used as a *relative, within-niche screening signal* (not a guaranteed $/hr prediction). Surfaces the best opportunities via a Discord bot and ranked CLI output.

- **Pipeline B — Clip Factory** ([`PIPELINE_B_CLIP_FACTORY.md`](PIPELINE_B_CLIP_FACTORY.md))
  For campaigns you approve, acquires the source footage, sends it to a hosted clipping engine, matches finished clips back to live campaigns, and presents a local review dashboard with the best-matched campaign, its requirements, and a suggested caption. **Posting stays manual, one account per platform.**

## Principles

- **Compliance first.** Respect `robots.txt` and each source's terms. Detect blocks/challenges, log the URL, and **drop the source rather than evade** it. Sources that forbid automated access are handled by manual capture, never circumvention.
- **No auto-posting, no multi-account automation.** The system ranks and produces; the human posts. This keeps accounts clear of the behavior that gets clippers banned or unpaid.
- **Honest scoring.** Every user-facing number is an estimated screening signal, not a payout guarantee. Observed factors and guessed factors are tracked separately.
- **Small footprint.** Python + SQLite, single-process, single small box.

## Tech stack

Python 3.11+ · SQLite (WAL) · SQLAlchemy 2.x + Alembic · APScheduler · httpx · discord.py · FastAPI (Pipeline B dashboard) · pytest

## Status

Design phase. See the two documents above for the full architecture, data model, phased build plans, and open risks. No implementation code yet.
