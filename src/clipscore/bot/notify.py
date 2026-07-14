"""Alert selection and movers analysis over the eligible latest-score board.
Pure of Discord; returns plain dicts for the formatting/dispatch layers."""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.db.models import CampaignScore, CampaignSnapshot
from clipscore.scoring.board import eligible_latest_scores
from clipscore.bot.state import already_alerted

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _latest_epoch(session: Session, campaign_id: str) -> int:
    # Dedup epoch = the campaign's latest snapshot epoch AT DISPATCH TIME. Correct
    # only because poll_and_alert runs ingest->score->dispatch in one process with
    # no intervening ingest, so this reflects the epoch the current score was for.
    s = session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(CampaignSnapshot.id.desc()).limit(1)
    ).scalars().first()
    return s.epoch if s is not None else 0


def select_alerts(session: Session, alert_percentile: float, min_niche_sample: int,
                  now_iso: str) -> list[dict]:
    pairs = eligible_latest_scores(session)
    # valid population per niche = eligible campaigns with a non-None percentile
    by_niche: dict[str, list] = {}
    for c, s in pairs:
        if s.cvs_niche_percentile is None:
            continue
        by_niche.setdefault(c.niche or "other", []).append((c, s))
    out = []
    for niche, members in by_niche.items():
        if len(members) < min_niche_sample:
            continue
        for c, s in members:
            if s.cvs_niche_percentile < alert_percentile:
                continue
            epoch = _latest_epoch(session, c.id)
            if already_alerted(session, c.id, epoch):
                continue
            out.append(dict(campaign_id=c.id, title=c.title, niche=niche, url=c.url,
                            percentile=s.cvs_niche_percentile, cvs_raw=s.cvs_raw, epoch=epoch))
    return out


def compute_movers(session: Session, now_iso: str, window_hours: int = 24,
                   top_n: int = 5) -> list[dict]:
    cutoff_iso = (datetime.strptime(now_iso, _FMT) - timedelta(hours=window_hours)).strftime(_FMT)
    movers = []
    for c, latest in eligible_latest_scores(session):
        if latest.cvs_niche_percentile is None:
            continue
        past = session.execute(
            select(CampaignScore).where(CampaignScore.campaign_id == c.id,
                                        CampaignScore.scored_at <= cutoff_iso)
            .order_by(CampaignScore.scored_at.desc(), CampaignScore.id.desc()).limit(1)
        ).scalars().first()
        if past is None or past.cvs_niche_percentile is None:
            continue
        delta = latest.cvs_niche_percentile - past.cvs_niche_percentile
        movers.append(dict(campaign_id=c.id, title=c.title, niche=c.niche or "other",
                           current=latest.cvs_niche_percentile,
                           past=past.cvs_niche_percentile, delta=delta))
    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return movers[:top_n]
