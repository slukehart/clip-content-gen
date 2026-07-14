"""APScheduler entrypoint: poll contentrewards on an interval and ingest."""
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.upsert import run_ingest_batch
from clipscore.scoring.engine import score_all
from clipscore.factory.enrich import enrich_batch

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
    return sched
