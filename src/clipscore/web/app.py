import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from clipscore.config import Settings, get_settings
from clipscore.db.models import Clip
from clipscore.db.session import SessionLocal, get_engine
from clipscore.web import actions, queries
from clipscore.web import warnings as dupwarn

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def get_db():
    """One short-lived session per request. Tests override this."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Bind SessionLocal to the configured engine (idempotent side effect).
    get_engine()
    app = FastAPI(title="clipscore review")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES))
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    templates = app.state.templates

    @app.get("/", response_class=HTMLResponse)
    def approval(request: Request, db: Session = Depends(get_db)):
        return templates.TemplateResponse(request, "approval.html", {
            "rows": queries.approval_rows(db, settings),
            "monthly_cost": queries.monthly_cost_usd(db),
        })

    @app.post("/clip/{campaign_id}", response_class=HTMLResponse)
    def clip(campaign_id: str, request: Request, db: Session = Depends(get_db)):
        result = actions.clip_this(db, campaign_id, settings)
        return templates.TemplateResponse(request, "_clip_button.html", {
            "campaign_id": campaign_id, "result": result,
        })

    @app.get("/review", response_class=HTMLResponse)
    def review_list(request: Request, db: Session = Depends(get_db)):
        return templates.TemplateResponse(request, "review_list.html", {
            "clips": queries.ready_clips(db),
        })

    @app.get("/review/{clip_id}", response_class=HTMLResponse)
    def review(clip_id: int, request: Request, db: Session = Depends(get_db)):
        detail = queries.review_detail(db, clip_id)
        if detail is None:
            raise HTTPException(status_code=404)
        warns = {m.match_id: dupwarn.duplicate_warnings(db, clip_id, m.campaign_id)
                 for m in detail.matches}
        return templates.TemplateResponse(request, "review.html", {
            "detail": detail, "warnings": warns,
        })

    @app.get("/media/{clip_id}")
    def media(clip_id: int, db: Session = Depends(get_db)):
        clip = db.get(Clip, clip_id)
        if clip is None or not clip.storage_uri:
            raise HTTPException(status_code=404)
        real = os.path.realpath(clip.storage_uri)
        media_root = os.path.realpath(settings.media_dir)
        if not (real == media_root or real.startswith(media_root + os.sep)):
            raise HTTPException(status_code=404)
        if not os.path.isfile(real):
            raise HTTPException(status_code=404)
        return FileResponse(real)

    @app.post("/posted/{match_id}", response_class=HTMLResponse)
    def posted(match_id: int, request: Request, db: Session = Depends(get_db)):
        result = actions.mark_posted(db, match_id)
        return templates.TemplateResponse(request, "_posted.html", {
            "result": result,
        })

    @app.get("/manual", response_class=HTMLResponse)
    def manual_form(request: Request):
        return templates.TemplateResponse(request, "manual.html", {"result": None})

    @app.post("/manual", response_class=HTMLResponse)
    def manual_submit(request: Request, db: Session = Depends(get_db),
                      title: str = Form(...), niche: str = Form(""),
                      content_bank_url: str = Form(""), target_creator: str = Form(""),
                      source_minutes: str = Form("")):
        est_minutes = int(source_minutes) if source_minutes.strip() else None
        result = actions.create_manual_campaign(
            db, title=title, niche=niche or None,
            content_bank_url=content_bank_url or None,
            target_creator=target_creator or None, est_minutes=est_minutes, settings=settings,
        )
        return templates.TemplateResponse(request, "manual.html", {"result": result})

    return app
