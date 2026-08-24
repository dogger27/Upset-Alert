---
name: db-pull
description: Download a snapshot of the PRODUCTION database to local — backs up prod and refreshes the local dev DB so the local site shows real data.
---

# db-pull — pull the production database down to local

Pulls a **consistent snapshot of the LIVE production SQLite database** from the
Jupiter server down to this machine. It serves two purposes at once:
1. **Backs up production** (a timestamped copy is saved under `backend/db_backups/`).
2. **Refreshes the local dev DB** (`backend/tennis_fantasy.db`) so the local site
   shows real production data instead of the stale/unusable local data.

## ⚠️ Direction is ALWAYS prod → local. NEVER local → prod.
Every command below only **reads** the production DB and only **writes** files
under the project. There is no step that writes to the server.

**This matters more than it used to.** Both databases are on this one machine —
there is no `ssh`/`scp` hop to get the direction wrong in, just two paths in the
same filesystem. A `cp` with its arguments the wrong way round overwrites live
production instantly, with no network boundary to stop it. Read every `cp` in
this file left-to-right before running it.

Paths:
- Prod DB (this host): `/home/paulwiens/upsetalert/data/tennis_fantasy.db` — **read only**
- Local working DB: `backend/tennis_fantasy.db` (what `/run` uses) — the only write target

## Steps

1. **Snapshot prod** (read-only; `.backup` is safe on a live DB, unlike `cp`,
   which can catch a torn write and misses the WAL):
```
sqlite3 /home/paulwiens/upsetalert/data/tennis_fantasy.db ".backup /tmp/tfl_snapshot.db"
```

2. There is **no download step** — this session runs on the production host, so
   the snapshot is already a local file. Do not `scp`/`ssh` it from `jupiter`:
   that fails outright (`Permission denied`), because the host holds no key
   authorising itself. Leave `/tmp/tfl_snapshot.db` in place until step 4 has
   copied it; deleting it here would throw away the thing being pulled.

3. **Sanity-check** the snapshot before using it (must be a valid, non-trivial DB):
```
test -s /tmp/tfl_snapshot.db && sqlite3 /tmp/tfl_snapshot.db "select count(*) from users;"
```
If this errors or returns 0, STOP — do not overwrite the local DB.

4. **Save the timestamped prod backup**:
```
mkdir -p backend/db_backups
cp /tmp/tfl_snapshot.db "backend/db_backups/tennis_fantasy_$(date +%Y%m%d_%H%M%S).db"
```

5. **Refresh the local working DB** (keep the previous local one aside just in case):
```
[ -f backend/tennis_fantasy.db ] && cp backend/tennis_fantasy.db /tmp/local_db_before_pull.db
cp /tmp/tfl_snapshot.db backend/tennis_fantasy.db
```

6. If the local backend is running, **restart it** (re-run `/run`) so it opens the
   new file. SQLite is opened at startup; an already-running server keeps the old data.

7. **Remove the snapshot** now that it has been copied:
```
rm -f /tmp/tfl_snapshot.db
```

## Notes
- `*.db` is gitignored, so `backend/tennis_fantasy.db` and everything in
  `backend/db_backups/` never reach git or a deploy — no risk of clobbering prod.
- The local copy is a **point-in-time snapshot**, not live. Re-run this skill
  whenever you want fresh production data locally.
- Old backups accumulate in `backend/db_backups/`; prune manually if desired.
