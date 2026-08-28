import asyncio
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
import app.models.passkey  # noqa: F401
import app.models.prediction  # noqa: F401
import app.models.league  # noqa: F401
import app.models.tournament  # noqa: F401
import app.models.rankings  # noqa: F401
import app.models.h2h  # noqa: F401
import app.models.system_log  # noqa: F401
from app.services.scheduler import start_scheduler, stop_scheduler
from app.core.config import settings
from app.routers import admin, auth, contact, discovery, h2h, leagues, passkeys, predictions, push, schedule, stream, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # The write-txn watchdog: names any transaction held >20s with the stack
    # from its BEGIN. See database.py — installed after a day of lock storms
    # whose holder no outside tool could identify.
    from app.database import txn_watchdog
    asyncio.create_task(txn_watchdog())
    # Only production runs the background scrapers (Wikipedia / Tennis Explorer /
    # ELO / ESPN / Wikimedia EventStreams). Local dev (environment=development)
    # leaves them off so it doesn't duplicate load / trip rate limits.
    # Say it at boot, loudly, and in both directions. A staging box that is
    # silently emailing real users and a staging box that is silently NOT are
    # both bad, and the only difference is one flag — so neither state is left
    # to be inferred from the absence of a log line.
    if not settings.outbound_notifications:
        logging.getLogger("app").warning(
            "OUTBOUND NOTIFICATIONS DISABLED — email and Web Push will be "
            "blocked at the send call. Correct for staging; on production this "
            "means nobody is being notified of anything.")

    scrapers_on = settings.environment == "production"
    if scrapers_on:
        start_scheduler()

    # Independent of the scheduler on purpose: this is the one thing staging is
    # for, and it must be switchable there without also turning on every scraper
    # — or turned off in production without stopping them.
    live_on = settings.sofascore_live_enabled
    if live_on:
        from app.services.sofascore_live import monitor as sofa_live_monitor
        sofa_live_monitor.start()
        logging.getLogger("app").info("Sofascore live polling ENABLED")

    # The identity layer every one of the sweeps below reads. Without it a draw
    # is invisible to all of them and shows no live score at all, silently — see
    # the note in sofa_resolver.py for how that went unnoticed for two days.
    if settings.sofascore_live_enabled or settings.sofascore_results_enabled:
        from app.services import sofa_resolver
        asyncio.create_task(sofa_resolver.start())

    # Shadow results sweep. Independent of the live flag: it answers a different
    # question (who won) on a different cadence, and writes only sofa_* columns
    # that nothing reads except scripts/sofa_diff.
    # The order of play on its own, for an instance running without the full
    # scheduler. A no-op when the scheduler is running, which already owns it.
    oop_only = settings.order_of_play_enabled and not scrapers_on
    if oop_only:
        from app.services.scheduler import (
            run_order_of_play_only, run_schedule_estimates_only)
        asyncio.create_task(run_order_of_play_only())
        # Its own task on its own cadence — see the note there for why the
        # sheet's hour is the wrong interval for a job that talks to nobody.
        asyncio.create_task(run_schedule_estimates_only())
        logging.getLogger("app").info(
            "Order-of-play refresh ENABLED without the rest of the scrapers")

    doubles_on = settings.sofascore_doubles_enabled
    if doubles_on:
        from app.services.sofascore_doubles import monitor as sofa_doubles_monitor
        sofa_doubles_monitor.start()
        logging.getLogger("app").info("Sofascore doubles scoring ENABLED")

    results_on = settings.sofascore_results_enabled
    if results_on:
        from app.services.sofascore_results import monitor as sofa_results_monitor
        sofa_results_monitor.start()
        logging.getLogger("app").info(
            "Sofascore results sweep ENABLED (shadow columns only)")
        # And the thing that decides when "shadow" stops being true. It holds
        # the gate shut until the evidence is there, opens it once, and puts
        # ESPN back in charge if a winner ever disagrees afterwards.
        from app.services import sofa_cutover
        asyncio.create_task(sofa_cutover.start())
    else:
        logging.getLogger("app").info(
            "Scrapers/scheduler DISABLED (environment=%s). Set ENVIRONMENT=production to enable.",
            settings.environment,
        )
    yield
    if doubles_on:
        from app.services.sofascore_doubles import monitor as sofa_doubles_monitor
        sofa_doubles_monitor.stop()
    if results_on:
        from app.services.sofascore_results import monitor as sofa_results_monitor
        sofa_results_monitor.stop()
    if live_on:
        from app.services.sofascore_live import monitor as sofa_live_monitor
        sofa_live_monitor.stop()
    if scrapers_on:
        stop_scheduler()
    # Close every pooled connection so SQLite runs its closing checkpoint and
    # folds the WAL back into the database file. Not a correctness requirement
    # now that the WAL lives on the host (see docker-compose.yml), but it keeps
    # the .db file current between deploys, which is what the nightly backup
    # and any out-of-band read see.
    from app.database import engine
    await engine.dispose()


app = FastAPI(title="Tennis Fantasy League", version="0.1.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
ALLOWED_ORIGINS = [
    "http://localhost:5173",        # Vite dev server
    "https://upsetalert.ca",        # Primary domain
    "https://www.upsetalert.ca",    # www variant
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(passkeys.router)
app.include_router(contact.router)
app.include_router(tournaments.router)
app.include_router(discovery.router)
app.include_router(leagues.router)
app.include_router(predictions.router)
app.include_router(h2h.router)
app.include_router(push.router)
app.include_router(schedule.router)
app.include_router(stream.router)


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
    # Starlette installs a bare `Exception` handler on ServerErrorMiddleware,
    # which wraps the user middleware stack — so this response never passes
    # back through CORSMiddleware and carries no Access-Control-Allow-Origin.
    # The browser then reports every 500 as "blocked by CORS policy", hiding
    # the actual failure: a genuine server error looked like a CORS
    # misconfiguration, and the client only ever saw "Unknown error".
    origin = request.headers.get("origin")
    headers = {}
    if origin in ALLOWED_ORIGINS:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error"}, headers=headers,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


_UNSUB_PREF_LABELS = {
    "round_standings": "round-completion emails",
    "match_start": "match-start emails",
    # Key is historical; the notification is "Draw Completion" everywhere users see it.
    "tournament_end": "draw-completion emails",
    "draw_released": "draw-release emails",
    "draw_changed": "draw-change emails",
    "qualifiers_added": "qualifier emails",
    "standout_pick": "standout-pick emails",
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
    from sqlalchemy import delete, select
    from app.core.security import verify_unsubscribe_token
    from app.database import AsyncSessionLocal
    from app.models.notification import NotificationOptOut, NotificationPreference

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
        # Record the refusal, not just the removal. Notifications are on by
        # default, so deleting the preference alone would be undone by the next
        # enrolment pass — an unsubscribe link that quietly re-subscribes, which
        # is the one failure this page must never have.
        exists = (await db.execute(
            select(NotificationOptOut).where(
                NotificationOptOut.user_id == user_id,
                NotificationOptOut.pref_key == pref_key,
            )
        )).scalar_one_or_none()
        if exists is None:
            db.add(NotificationOptOut(user_id=user_id, pref_key=pref_key))
        await db.commit()
    label = _UNSUB_PREF_LABELS.get(pref_key, "the selected email type")
    return HTMLResponse(_unsubscribe_page(f"You have been unsubscribed from {label}."))

@app.get("/debug/tasks/{key}")
async def debug_tasks(key: str):
    """TEMPORARY forensic endpoint (2026-08-25 lock/hang storms): every asyncio
    task's current stack. py-spy shows threads; the hangs live in tasks. Keyed
    rather than admin-authed so it works even when the auth path itself hangs."""
    if key != "wedge-hunt-7391":
        from fastapi import HTTPException
        raise HTTPException(404)
    import traceback
    out = []
    for t in asyncio.all_tasks():
        frames = t.get_stack(limit=8)
        out.append({
            "name": t.get_name(),
            "stack": ["".join(traceback.format_stack(f, limit=1)).strip()
                      for f in frames][-6:],
        })
    return out

