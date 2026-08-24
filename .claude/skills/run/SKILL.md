---
description: Launch the Tennis Fantasy League app (FastAPI backend + Vite frontend)
---

# Run — Tennis Fantasy League

Launches both servers so the app is fully functional. Each start first refreshes
the local database from **production** so the local site shows real data.

## Steps

1. **Refresh the local DB from production** (stop any running backend first so the
   SQLite file isn't held open while we overwrite it). Direction is ALWAYS
   prod → local; never the reverse. Non-fatal — if Jupiter is unreachable, keep
   the existing local DB and continue.

Runs on the production host itself, so there is no ssh/scp hop: the snapshot is
written straight to a local temp file. `.backup` rather than `cp` — it is the
only safe way to copy a live SQLite DB, and the only one that includes the WAL.

```bash
cd /home/paulwiens/Documents/Claude/Projects/TennisFantasyLeague
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
if sqlite3 /home/paulwiens/upsetalert/data/tennis_fantasy.db ".backup /tmp/tfl_snapshot.db" \
   && test -s /tmp/tfl_snapshot.db; then
  cp /tmp/tfl_snapshot.db backend/tennis_fantasy.db
  rm -f /tmp/tfl_snapshot.db
  echo "✓ Local DB refreshed from production ($(sqlite3 backend/tennis_fantasy.db 'select count(*) from users;') users)"
else
  echo "⚠ Could not snapshot prod DB — continuing with existing local DB"
fi
```

2. **Start the backend** (FastAPI via uvicorn, port 8000):

```bash
cd /home/paulwiens/Documents/Claude/Projects/TennisFantasyLeague/backend
.venv/bin/python -m uvicorn app.main:app --reload --port 8000 > /tmp/backend.log 2>&1 &
echo "Backend PID: $!"
```

3. **Wait and verify** the backend is up:

```bash
sleep 3 && curl -s http://localhost:8000/docs -o /dev/null -w "%{http_code}"
```
Expected: `200`. If not, check `/tmp/backend.log`.

4. **Start the frontend** (Vite dev server, port 5173):

```bash
cd /home/paulwiens/Documents/Claude/Projects/TennisFantasyLeague/frontend
npm run dev > /tmp/frontend.log 2>&1 &
echo "Frontend PID: $!"
```

5. **Verify** the frontend is up:

```bash
sleep 3 && cat /tmp/frontend.log
```
Expected: `VITE ... ready` and `Local: http://localhost:5173/`.

## URLs

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs

## Notes

- The backend uses a venv at `backend/.venv/` — always use `.venv/bin/python`, not system `python3`.
- Logs: `/tmp/backend.log`, `/tmp/frontend.log`
- The `python` command does not exist on this machine; use `python3` or the venv path.
- The DB refresh here does NOT save a timestamped backup (would pile up on every
  restart). Use `/db-pull` when you want a saved backup under `backend/db_backups/`.
- Local dev runs `environment=development`, so the backend does NOT scrape
  (Wikipedia / TE / ELO / ESPN / EventStreams are production-only).
