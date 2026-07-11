import logging
import logging.handlers
import os
from contextlib import asynccontextmanager

import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import init_db


def _setup_logging() -> None:
    log_file = os.environ.get("LOG_FILE")
    if not log_file:
        return
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s pid=%(process)d %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # EventStreams gets DEBUG so we see every enwiki event
    logging.getLogger("app.services.eventstream").setLevel(logging.DEBUG)


_setup_logging()
# Import models in dependency order so SQLAlchemy can resolve relationships
import app.models.user  # noqa: F401
import app.models.prediction  # noqa: F401
import app.models.league  # noqa: F401
import app.models.tournament  # noqa: F401
import app.models.rankings  # noqa: F401
import app.models.h2h  # noqa: F401
import app.models.system_log  # noqa: F401
from app.services.scheduler import start_scheduler, stop_scheduler
from app.core.config import settings
from app.routers import admin, auth, contact, discovery, h2h, leagues, predictions, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Only production runs the background scrapers (Wikipedia / Tennis Explorer /
    # ELO / ESPN / Wikimedia EventStreams). Local dev (environment=development)
    # leaves them off so it doesn't duplicate load / trip rate limits.
    scrapers_on = settings.environment == "production"
    if scrapers_on:
        start_scheduler()
    else:
        logging.getLogger("app").info(
            "Scrapers/scheduler DISABLED (environment=%s). Set ENVIRONMENT=production to enable.",
            settings.environment,
        )
    yield
    if scrapers_on:
        stop_scheduler()


app = FastAPI(title="Tennis Fantasy League", version="0.1.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",        # Vite dev server
        "https://upsetalert.ca",        # Primary domain
        "https://www.upsetalert.ca",    # www variant
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(contact.router)
app.include_router(tournaments.router)
app.include_router(discovery.router)
app.include_router(leagues.router)
app.include_router(predictions.router)
app.include_router(h2h.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    tb = traceback.format_exc()
    from app.services.system_log import app_log
    await app_log(
        "error", "api",
        f"{type(exc).__name__} on {request.method} {request.url.path}: {exc}",
        {"method": request.method, "path": str(request.url.path),
         "error": str(exc), "traceback": tb},
        dedup_key=f"api_{request.method}_{request.url.path}_{type(exc).__name__}",
        dedup_hours=1.0,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health():
    return {"status": "ok"}


_UNSUB_PREF_LABELS = {
    "round_standings": "round-completion emails",
    "match_start": "match-start emails",
    "tournament_end": "tournament-completion emails",
    "draw_released": "draw-release emails",
}


def _unsubscribe_page(message: str, ok: bool = True) -> str:
    accent = "#1b4332" if ok else "#b91c1c"
    icon = "✓" if ok else "!"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upset Alert — Unsubscribe</title></head>
<body style="margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6">
  <div style="max-width:480px;margin:64px auto;padding:0 20px">
    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
      <div style="background:{accent};padding:28px 24px;text-align:center">
        <div style="width:56px;height:56px;line-height:56px;margin:0 auto;border-radius:28px;
             background:rgba(255,255,255,0.15);color:#fff;font-size:28px;font-weight:700">{icon}</div>
      </div>
      <div style="padding:28px 24px;text-align:center">
        <h1 style="font-size:20px;margin:0 0 12px;color:#111">{message}</h1>
        <p style="color:#6b7280;line-height:1.6;margin:0 0 20px;font-size:14px">
          You can re-enable this any time from your notification settings on Upset Alert.
        </p>
        <a href="https://upsetalert.ca" style="display:inline-block;padding:11px 22px;
           background:#1b4332;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px">
          Go to Upset Alert
        </a>
      </div>
    </div>
  </div>
</body></html>"""


@app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str = ""):
    from sqlalchemy import delete
    from app.core.security import verify_unsubscribe_token
    from app.database import AsyncSessionLocal
    from app.models.notification import NotificationPreference

    result = verify_unsubscribe_token(token)
    if not result:
        return HTMLResponse(
            _unsubscribe_page("This unsubscribe link is invalid or has expired.", ok=False),
            status_code=400,
        )
    user_id, pref_key = result
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.pref_key == pref_key,
            )
        )
        await db.commit()
    label = _UNSUB_PREF_LABELS.get(pref_key, "the selected email type")
    return HTMLResponse(_unsubscribe_page(f"You have been unsubscribed from {label}."))
