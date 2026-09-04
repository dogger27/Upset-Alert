# tools/ — dev-only tooling

Deliberately its own package. Nothing here is a dependency of `mobile/` or
`frontend/`, so neither an EAS build nor a Cloudflare Pages build ever installs
Playwright.

## visual-diff.mjs — the app beside the site

Renders the Expo app and the PWA side by side at phone size, on the **same
data**, and writes `shots/<screen>.compare.png`.

It exists because every design correction was otherwise costing a round trip
through a screenshot taken on the phone.

```bash
node visual-diff.mjs                  # every screen
node visual-diff.mjs draw dashboard   # just these
node visual-diff.mjs --full           # full-page instead of one viewport
node visual-diff.mjs --scale=1.7      # the app at the phone's LARGER text size
```

`--scale` renders the app side at a given text-size multiplier (the phone has
larger text on; react-native-web always reports 1). Output goes to
`<screen>@1.7.*.png` so the 1.0 set is kept. Every app capture also reads
Expo's red-box overlay text and reports it as `RED BOX …` — a crash is painted
as an overlay, not thrown to `pageerror`, so a dark screenshot is not "fine".

### What it needs running

| Port | What | Started with |
|---|---|---|
| 8010 | local backend, local DB copy | `backend/.venv/bin/python -m uvicorn app.main:app --port 8010` |
| 8099 | the Expo app, web target | `EXPO_PUBLIC_API_URL=http://localhost:8010 npx expo start --web --port 8099` |
| 5173 | the PWA | `VITE_API_URL=http://localhost:8010 npm run dev -- --port 5173` |
| — | a token at `/tmp/ua_token.txt` | `create_access_token('1')` from `app.core.security` |

Refresh the local DB first, or the comparison is against stale draws. STOP
the local backend before copying and delete the copy's `-wal`/`-shm`
siblings: a running backend leaves its write-ahead log next to the file, and
the next open replays that OLD log into the NEW copy — "malformed database
schema" on startup (paid for on 2026-09-04).

```bash
kill $(ss -ltnp | grep ':8010' | grep -o 'pid=[0-9]*' | cut -d= -f2)
rm -f backend/tennis_fantasy.db-wal backend/tennis_fantasy.db-shm
sqlite3 /home/paulwiens/upsetalert/data/tennis_fantasy.db \
  ".backup /tmp/s.db" && cp /tmp/s.db backend/tennis_fantasy.db
```

The local backend must NOT have `ENVIRONMENT=production`: that gate is the only
thing keeping scrapers, the scheduler and outbound email switched off.

### DO NOT point port 8081 at the local backend

8081 is the Metro the **phone's development build** attaches to. It must run
with no `EXPO_PUBLIC_API_URL` so the bundle keeps its production default;
otherwise the phone gets a bundle aimed at a `localhost` it cannot reach and the
app simply fails to load with no obvious cause. The harness uses 8099 for
exactly this reason. Check before assuming:

```bash
tr '\0' '\n' < /proc/$(pgrep -f "expo start" | head -1)/environ | grep EXPO_PUBLIC || echo "clean"
```

### What it can and cannot tell you

It renders through **react-native-web**, not iOS.

- **Trust it for**: layout, hierarchy, spacing, type scale, colour, wrapping and
  truncation, whether data is actually reaching a screen.
- **Do not trust it for**: shadows, safe-area insets (the tab bar looks clipped
  here and is fine on device), native font rendering, gestures.
- **It cannot render flag emoji at all** — this machine has no colour emoji
  font, so flags show as empty boxes. iOS draws them natively.

Both contexts are pinned to `America/Vancouver`, not Chromium's default UTC.
With both sides in UTC a real disagreement about whose clock to show rendered
as agreement — which is how the draw shipped "Tomorrow at ~1:00 a.m. UTC" where
the site said "Today at ~6:00 p.m. PDT".

Chromium runs with web security disabled purely so two localhost origins may
call the local backend without an allowlist entry. Throwaway profile, local
token, local database.
