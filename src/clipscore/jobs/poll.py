"""APScheduler entrypoint: poll contentrewards on an interval and ingest."""
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.upsert import run_ingest_batch
from clipscore.scoring.engine import score_all

log = structlog.get_logger()
_MISS_COUNTS: dict[str, int] = {}

def run_once(session) -> dict:
    result = run_ingest_batch(session, ContentrewardsIngester(), miss_counts=_MISS_COUNTS)
    log.info("ingest_batch", **result)
    if result.get("status") == "ok":
        score_result = score_all(session)
        log.info("scoring", **score_result)
        result["scored"] = score_result["scored"]
    return result

def build_scheduler(session_factory) -> BackgroundScheduler:
    sched = BackgroundScheduler()
    minutes = get_settings().poll_interval_minutes
    def job():
        with session_factory() as s:
            run_once(s)
    sched.add_job(job, "interval", minutes=minutes, id="contentrewards_poll")
    return sched
