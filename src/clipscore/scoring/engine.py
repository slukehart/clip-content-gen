"""Scoring engine: gather DB inputs, run the pure formula, write campaign_scores.
Scored population = active + ingestable + not-UGC. Cross-niche placement is NOT
trustworthy in v1; cvs_niche_percentile (within-niche) is the user-facing signal."""
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.db.models import (Campaign, CampaignSnapshot, CampaignScore,
                                 NicheBaseline, PlatformTrust)
from clipscore.scoring import formula
from clipscore.scoring.budget import budget_health
from clipscore.scoring.percentile import empirical_cdf

log = structlog.get_logger()


def _snapshots_for(session: Session, campaign_id: str) -> list[CampaignSnapshot]:
    return session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
    ).scalars().all()


def _baseline(baselines: dict, niche) -> NicheBaseline:
    key = niche or "other"
    return baselines.get(key) or baselines["other"]


def score_all(session: Session, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    settings = get_settings()

    campaigns = session.execute(select(Campaign)).scalars().all()

    baselines = {b.niche: b for b in session.execute(select(NicheBaseline)).scalars().all()}
    trust = {t.source: t for t in session.execute(select(PlatformTrust)).scalars().all()}

    res = {"scored": 0, "skipped_ugc": 0, "skipped_walled": 0, "zero_cpm": 0}
    # collect (record, niche_key, cvs_or_None) so we can compute percentiles after
    pending = []
    for c in campaigns:
        if c.status != "active":
            continue
        if c.access_status != "ingestable":
            res["skipped_walled"] += 1
            continue
        if c.campaign_type == "ugc":
            res["skipped_ugc"] += 1
            continue

        pt = trust.get(c.source)
        fee = pt.default_fee_pct if pt else 0.0
        p_payout = pt.trust_score if pt else 0.0
        base = _baseline(baselines, c.niche)
        niche_key = c.niche or "other"

        snaps = _snapshots_for(session, c.id)
        latest = max(snaps, key=lambda s: s.captured_at) if snaps else None
        remaining_now = latest.budget_remaining_usd if latest else None
        clippers_now = latest.active_clippers if latest else None

        if c.cpm_usd is None or c.cpm_usd <= 0:
            log.warning("zero_or_missing_cpm", campaign_id=c.id, cpm=c.cpm_usd)
            res["zero_cpm"] += 1
            rec = dict(campaign_id=c.id, net_cpm=0.0, capped_earnings=0.0,
                       p_threshold=0.0, p_approval=0.0,
                       p_payout=0.0, budget_health=0.0, sat_factor=0.0,
                       ev_per_clip=0.0, cvs_raw=0.0)
            pending.append((rec, niche_key, None))   # None -> excluded from percentile
            res["scored"] += 1
            continue

        ncpm = formula.net_cpm(c.cpm_usd, fee)
        raw = formula.raw_earnings(ncpm, base.e_views_median)
        capped = formula.capped_earnings(raw, c.cap_per_post_usd, c.cap_provenance,
                                         settings.default_assumed_cap_usd)
        bh = budget_health(snaps, now_iso)
        sat = formula.sat_factor(remaining_now, clippers_now)
        ev = formula.ev_per_clip(capped, base.p_threshold, settings.default_p_approval,
                                 p_payout, bh, sat)
        cvs = formula.cvs_raw(ev, settings.hours_per_clip)
        rec = dict(campaign_id=c.id, net_cpm=ncpm, capped_earnings=capped,
                   p_threshold=base.p_threshold, p_approval=settings.default_p_approval,
                   p_payout=p_payout, budget_health=bh, sat_factor=sat,
                   ev_per_clip=ev, cvs_raw=cvs)
        pending.append((rec, niche_key, cvs))
        res["scored"] += 1

    # percentile population per niche = valid (non-excluded) cvs only
    pops: dict[str, list[float]] = {}
    for _, niche_key, cvs in pending:
        if cvs is not None:
            pops.setdefault(niche_key, []).append(cvs)

    for rec, niche_key, cvs in pending:
        pct = empirical_cdf(cvs, pops[niche_key]) if cvs is not None else None
        session.add(CampaignScore(scored_at=now_iso, cvs_niche_percentile=pct, **rec))
    session.commit()
    return res
