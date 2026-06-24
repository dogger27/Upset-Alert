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
from fastapi.responses import JSONResponse

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
from app.routers import admin, auth, contact, discovery, h2h, leagues, predictions, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
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
