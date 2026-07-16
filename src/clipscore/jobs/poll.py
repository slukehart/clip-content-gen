"""APScheduler entrypoint: poll contentrewards on an interval and ingest."""
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.upsert import run_ingest_batch
from clipscore.scoring.engine import score_all
from clipscore.factory.enrich import enrich_batch
from clipscore.jobs.clipfactory import process_clip_jobs

log = structlog.get_logger()
_MISS_COUNTS: dict[str, int] = {}

def run_once(session) -> dict:
    result = run_ingest_batch(session, ContentrewardsIngester(), miss_counts=_MISS_COUNTS)
    log.info("ingest_batch", **result)
    if result.get("status") == "ok":
        score_result = score_all(session)
        log.info("scoring", **score_result)
        result["scored"] = score_result["scored"]

        # Pipeline B extraction is a strictly best-effort post-ingest step: it
        # must NEVER affect the committed ingest/score result above. Guard
        # the entire call (including enrich_batch's own query/iteration,
        # which is not internally guarded) -- any failure here is logged and
        # swallowed, never propagated or reflected in `result`.
        try:
            extract_result = enrich_batch(session, get_settings(), only_stale=True)
            log.info("extraction", **extract_result)
        except Exception:
            log.error("extraction_failed", exc_info=True)
    return result

def build_scheduler(session_factory) -> BackgroundScheduler:
    sched = BackgroundScheduler()
    minutes = get_settings().poll_interval_minutes
    def job():
        with session_factory() as s:
            run_once(s)
    sched.add_job(job, "interval", minutes=minutes, id="contentrewards_poll")

    def clip_factory_job():
        with session_factory() as s:
            try:
                result = process_clip_jobs(s, get_settings())
                log.info("clip_factory", **result)
            except Exception:
                # Guarded: a clip-factory tick must never crash the
                # scheduler. process_clip_jobs itself never raises, but
                # this is defense-in-depth (e.g. failure opening the
                # session-scoped settings).
                log.error("clip_factory_tick_failed", exc_info=True)
    sched.add_job(clip_factory_job, "interval", minutes=minutes, id="clip_factory")

    def retention_job():
        with session_factory() as s:
            try:
                from clipscore.factory.clip.retention import sweep_clip_retention
                result = sweep_clip_retention(s, get_settings())
                log.info("clip_retention", **result)
            except Exception:
                log.error("clip_retention_tick_failed", exc_info=True)
    sched.add_job(retention_job, "interval", minutes=minutes, id="clip_retention")
    return sched
