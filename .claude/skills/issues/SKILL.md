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
