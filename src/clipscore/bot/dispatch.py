"""Transport-agnostic orchestration: select/format/send/record, and the combined
poll+alert cycle. The Discord adapter supplies a Notifier; failures here never
touch the already-committed ingest/score result."""
from typing import Protocol
import structlog
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.jobs.poll import run_once
from clipscore.scoring.board import eligible_latest_scores
from clipscore.bot.notify import select_alerts, compute_movers
from clipscore.bot.state import record_alert
from clipscore.bot.messages import format_alert, format_summary

log = structlog.get_logger()


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


def dispatch_alerts(session: Session, notifier: Notifier, settings, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    candidates = select_alerts(session, settings.alert_percentile,
                               settings.min_niche_sample, now_iso)
    sent = 0
    for c in candidates:
        try:
            notifier.send(format_alert(c))
        except Exception:
            log.warning("alert_send_failed", campaign_id=c["campaign_id"])
            continue   # not recorded -> retried next cycle
        record_alert(session, c["campaign_id"], c["epoch"], c["niche"], c["percentile"], now_iso)
        sent += 1
    return {"alerts_sent": sent}


def _top_per_niche(session: Session) -> list[dict]:
    best: dict[str, dict] = {}
    for c, s in eligible_latest_scores(session):
        if s.cvs_niche_percentile is None:
            continue
        niche = c.niche or "other"
        cur = best.get(niche)
        if cur is None or s.cvs_niche_percentile > cur["cvs_niche_percentile"]:
            best[niche] = dict(niche=niche, title=c.title,
                               cvs_niche_percentile=s.cvs_niche_percentile)
    return sorted(best.values(), key=lambda r: r["niche"])


def dispatch_summary(session: Session, notifier: Notifier, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    text = format_summary(_top_per_niche(session), compute_movers(session, now_iso), now_iso)
    try:
        notifier.send(text)
    except Exception:
        log.exception("summary_send_failed")
        return {"summary_sent": False}
    return {"summary_sent": True}


def poll_and_alert(session: Session, notifier: Notifier, settings=None,
                   now_iso: str | None = None) -> dict:
    result = run_once(session)   # ingest + score; Discord-free, already committed
    if result.get("status") == "ok":
        try:
            r = dispatch_alerts(session, notifier, settings or get_settings(), now_iso)
            result["alerts_sent"] = r["alerts_sent"]
        except Exception:
            log.exception("alert_dispatch_failed")   # never break ingest/score
    return result
