"""Clip-file retention for B5. Clips-only (passthrough keeps no source file).
`delete_clip_file` is the guarded single-file delete reused by mark-posted;
`sweep_clip_retention` prunes clip files older than `clip_retention_days`.
Both tolerate an already-missing file (never raise)."""
import os
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from clipscore.config import Settings
from clipscore.db.models import Clip

log = structlog.get_logger()


def delete_clip_file(clip: Clip) -> bool:
    """Remove a clip's on-disk file if present, and null its storage_uri.
    Returns True iff a file was actually removed. Never raises."""
    uri = clip.storage_uri
    removed = False
    if uri and os.path.isfile(uri):
        try:
            os.remove(uri)
            removed = True
        except OSError:
            log.warning("clip_file_delete_failed", clip_id=clip.id, storage_uri=uri)
    clip.storage_uri = None
    return removed


def _cutoff_iso(days: int, now: datetime | None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sweep_clip_retention(session, settings: Settings, now=None) -> dict:
    """Delete files of clips older than `clip_retention_days` (by created_at)."""
    cutoff = _cutoff_iso(settings.clip_retention_days, now)
    clips = session.execute(
        select(Clip).where(Clip.created_at < cutoff, Clip.storage_uri.is_not(None))
    ).scalars().all()
    pruned = 0
    for c in clips:
        if delete_clip_file(c):
            pruned += 1
    session.commit()
    return {"pruned": pruned}
