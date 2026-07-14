"""Snapshot retention: raw within raw_retention_days, hourly rollup beyond.
Only ever touches snapshots older than the window, so it can never affect the
48h budget-health burn window or the latest-per-epoch rows scoring reads."""
import structlog
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.db.models import CampaignSnapshot

log = structlog.get_logger()


def _parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")


def rollup_snapshots(session: Session, now_iso: str | None = None) -> dict:
    now = _parse(now_iso or utcnow_iso())
    cutoff = now - timedelta(days=get_settings().raw_retention_days)
    rows = session.execute(select(CampaignSnapshot)).scalars().all()
    # bucket old rows by (campaign_id, hour); keep max id per bucket
    buckets: dict[tuple, list[CampaignSnapshot]] = {}
    kept = 0
    for s in rows:
        if _parse(s.captured_at) >= cutoff:
            kept += 1
            continue
        key = (s.campaign_id, s.captured_at[:13])   # "YYYY-MM-DDTHH"
        buckets.setdefault(key, []).append(s)
    deleted = 0
    for group in buckets.values():
        group.sort(key=lambda s: s.id)
        for stale in group[:-1]:      # keep the last (max id) in the bucket
            session.delete(stale)
            deleted += 1
        kept += 1
    session.commit()
    log.info("snapshot_rollup", deleted=deleted, kept=kept)
    return {"deleted": deleted, "kept": kept}
