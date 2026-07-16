"""On-demand clip-job drain (`clipscore process`). `process_clip_jobs`
advances each in-flight job by one stage; draining loops it until a pass
advances nothing (every job reached matched/failed/blocked). This is the
operator's manual alternative to waiting for the bot scheduler's interval
tick -- `clipscore web`/`clip` only ENQUEUE jobs."""
import structlog

from clipscore.config import Settings
from clipscore.jobs.clipfactory import process_clip_jobs

log = structlog.get_logger()


def drain_clip_jobs(session, settings: Settings, *, once: bool = False,
                    engine=None, registry=None, llm=None, now=None) -> dict:
    passes = 0
    total_advanced = 0
    total_failed = 0
    while True:
        result = process_clip_jobs(session, settings, registry=registry,
                                   engine=engine, llm=llm, now=now)
        passes += 1
        total_advanced += result["advanced"]
        total_failed += result["failed"]
        if once or result["advanced"] == 0:
            break
    log.info("clip_drain", passes=passes, advanced=total_advanced, failed=total_failed)
    return {"passes": passes, "advanced": total_advanced, "failed": total_failed}
