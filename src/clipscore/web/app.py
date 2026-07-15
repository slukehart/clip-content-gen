from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from clipscore.config import Settings, get_settings
from clipscore.db.session import SessionLocal, get_engine
from clipscore.web import actions, queries

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
        return templates.TemplateResponse("approval.html", {
            "request": request,
            "rows": queries.approval_rows(db, settings),
            "monthly_cost": queries.monthly_cost_usd(db),
        })

    @app.post("/clip/{campaign_id}", response_class=HTMLResponse)
    def clip(campaign_id: str, request: Request, db: Session = Depends(get_db)):
        result = actions.clip_this(db, campaign_id, settings)
        return templates.TemplateResponse("_clip_button.html", {
            "request": request, "campaign_id": campaign_id, "result": result,
        })

    return app
