---
name: issues
description: Show the site's logged issues instantly — errors/warnings from production system_logs, their alert state, and (optionally) what was actually emailed via Resend.
---

# issues — the site's problems, straight from the source

The truth lives in the **production `system_logs` table**, not in the alert
emails: emails are a rate-limited digest of it (24h per-signature gate, 3/day
cap, 6h quiet cutoff — see `backend/app/services/alerts.py`). Query the DB
first; use Resend only to check what the user was actually *sent*.

## Primary: query production directly (read-only)

Default window 24h; adjust the `-24 hours` as asked ("/issues 48h" → `-48 hours`).

```bash
cd /home/paulwiens/upsetalert/app && docker compose exec -T backend python -c "
import sqlite3
c = sqlite3.connect('/data/tennis_fantasy.db')
rows = c.execute('''
  SELECT level, category, substr(message,1,150), count(*),
         min(created_at), max(created_at)
  FROM system_logs
  WHERE created_at > datetime('now','-24 hours') AND level IN ('error','warning')
  GROUP BY level, category, substr(message,1,60)
  ORDER BY max(created_at) DESC''').fetchall()
for lv, cat, msg, n, first, last in rows:
    print(f'{lv.upper():7} {cat:18} x{n:<3} {last[:16]}  {msg}')
print('---', len(rows), 'distinct issue groups in window')"
```

For one issue's full detail (swap the LIKE):

```bash
cd /home/paulwiens/upsetalert/app && docker compose exec -T backend python -c "
import sqlite3
c = sqlite3.connect('/data/tennis_fantasy.db')
for r in c.execute('''SELECT created_at, level, category, message, detail_json
  FROM system_logs WHERE message LIKE '%<KEYWORD>%'
  ORDER BY id DESC LIMIT 5'''): print(r)"
```

## Alert state — was it emailed, gated, or capped?

```bash
cd /home/paulwiens/upsetalert/app && docker compose exec -T backend python -c "
import sqlite3
c = sqlite3.connect('/data/tennis_fantasy.db')
for r in c.execute('''SELECT substr(fingerprint,1,10), last_alerted_at, alert_count
  FROM alert_signatures ORDER BY last_alerted_at DESC LIMIT 10'''): print(r)"
```

A row present in system_logs but absent from a recent email usually means the
24h gate, the 3/day cap, or the 6h quiet cutoff held it — that is the digest
working, not a delivery failure.

## Two suppressions, and only one of them survives a deploy

Do not read one as the other; they answer different questions.

| | Where it lives | Survives a restart? | What it gates |
|---|---|---|---|
| `app_log(dedup_key=…, dedup_hours=…)` | `_dedup_cache`, a plain dict in `services/system_log.py` — **no table** | **No** | whether a repeat reaches `system_logs` at all |
| `alert_signatures` | a table | Yes | whether a problem is emailed again |

Consequences when triaging:

- **A count in `system_logs` is occurrences since the last restart**, not the
  problem getting worse. `deploy.sh` runs on a 2-minute timer, so a busy
  afternoon of pushes re-arms every dedup key. The 65 rows for one broken
  Wikipedia title that prompted `AlertSignature` were one problem times many
  process generations.
- **A deploy is what makes "did it go quiet?" answerable.** Restarting clears
  the cache, so nothing suppresses the next check — if the fault is still
  there, the very next pass logs it. Wait for one full cycle of the job you
  fixed (the Sofascore resolver is hourly, `POLL_INTERVAL`, after a 120s
  `STARTUP_DELAY`), then query for rows newer than the container's
  `StartedAt`. Silence then is real evidence.
- Conversely, **24h of silence with no restart proves less** — the key may
  simply still be held.

## Fallback: what actually reached the inbox (Resend MCP)

Use `mcp__plugin_resend_resend__list-emails` (limit ~10) and look for subjects
starting "Upset Alert: N issues"; `get-email` with the ID shows the full body.
This answers "what did the user SEE", never "what is wrong right now".

## When play is disrupted (rain, light, anything)

The whole suspended → postponed → to-be-completed flow is automatic; see
memory `rain-delay-lifecycle`. To watch it live during a delay:

```bash
/home/paulwiens/Documents/Claude/Projects/TennisFantasyLeague/backend/.venv/bin/python \
  /home/paulwiens/upsetalert/verify/resume_watch.py
```

Run it with Monitor (persistent). It prints only suspensions, resumptions,
scoreless finishes and fetch failures. Edit the date at the top for the day in
question, and refresh the token with
`create_access_token('1')` if it 401s.

One query answers "is the disruption being handled?":

```bash
cd /home/paulwiens/upsetalert/app && docker compose exec -T backend python -c "
import sqlite3, json
c = sqlite3.connect('/data/tennis_fantasy.db')
for r in c.execute('''SELECT play_date, status, count(*) FROM schedule_entries
  WHERE play_date >= date('now','-1 day') GROUP BY play_date, status ORDER BY 1,2'''):
    print(r)"
```

Rows stuck at `scheduled` with a claim but no score mean the sweep cannot see
their events — check the upstream status STRING first (`/event/{id}`).

## House rules while triaging

- Every logged error gets fixed in-session, noise included; "fix this" means
  the whole bug class (see memory: fix-all-errors, audit-full-bug-class).
- Timestamps in the DB are UTC; the user's clock is Pacific (UTC-7).
- Expected pre-release states (WikiPageNotFound etc.) are not errors.
- After fixing, verify the signature goes quiet rather than deleting rows.
