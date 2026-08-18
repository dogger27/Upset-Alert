# Upset Alert 🎾

Pick every match in a tennis draw before it starts, then watch your bracket survive
contact with reality. Live at **[upsetalert.ca](https://upsetalert.ca)**.

Draws are scraped from Wikipedia as soon as editors publish them, picks lock at the
first ball, and scores update from live ESPN data as results come in.

## Features

- **Live brackets** — draws scraped from Wikipedia, refreshed via Wikimedia
  EventStreams so a late withdrawal or a named qualifier lands without a manual step
- **Predictions** — pick a winner for every match; picks lock automatically at the
  first scheduled match, with the deadline refined from ESPN's schedule as it firms up
- **Live scores** — in-progress set/game scores and match results polled from ESPN
- **Scoring** — four modes per league: Classic (doubling points), ATP/WTA Points
  Mirror, Upset Bonus, or Custom. Ties break round by round, Final backwards
- **Leagues** — create or join a league; a Global league everyone belongs to
- **Head-to-head** — career H2H and recent form for any two players in a draw,
  built from match history the app has already recorded
- **Hall of Fame & Draw History** — per-draw results kept for every entrant, with
  all-time records split by tier and tour
- **Notifications** — email and Web Push for draw releases, match starts, round
  completions and standings digests, on by default with recorded opt-outs
- **Installable PWA** — works as a standalone app on phone and desktop, dark mode
  by default with a light theme that follows the account

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy (async), SQLite (WAL) |
| Frontend | React 18, Vite, TanStack Query v5, Zustand |
| Draw data | Wikipedia API + Wikimedia EventStreams |
| Rankings | Tennis Explorer (rankings, ELO, nationality) |
| Live scores | ESPN public scoreboard API |
| Delivery | Resend (email), Web Push / VAPID |

## How the data pipeline fits together

Four services do most of the work, and they own different columns on purpose:

- `services/discovery.py` finds new tournaments from ATP/WTA season pages.
- `services/scraper.py` parses the Wikipedia bracket wikitext into matches and
  entrants. It owns draw structure, seeds and entry types. Before a draw is
  published its page simply does not exist — `WikiPageNotFound` is the routine
  answer during that window, not an error.
- `services/rankings.py` matches entrants to Tennis Explorer players for rankings
  and ELO, via token-set and fuzzy name matching.
- `services/espn_monitor.py` polls the ESPN scoreboard on a 60s loop and owns
  picks-locking, live scores, and match winners. One ESPN event maps to exactly
  one draw, resolved by name → player overlap (Jaccard) → venue city.

Because the scraper and ESPN both touch matches, the split matters: ESPN owns
`winner_id` and `completed_at`, and a re-scrape must not clear them.

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── core/          # config, security (JWT, bcrypt), middleware
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── routers/       # admin, auth, h2h, leagues, predictions, push, tournaments
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # scraper, rankings, espn_monitor, scoring, scheduler,
│   │   │                  # notifications, email, push, discovery
│   │   └── main.py
│   └── requirements.txt
└── frontend/
    └── src/
        ├── api/           # Axios API clients
        ├── components/    # BracketView, CombinedView, Navbar, design system
        ├── pages/         # Home, Tournaments, TournamentDraw, Leagues,
        │                  # LeagueDetail, HallOfFame, DrawHistory, Admin
        ├── store/         # auth + theme (Zustand)
        └── index.css      # design tokens; dark theme is a [data-theme] layer
```

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then set SECRET_KEY — see below
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8000`, matching uvicorn's dev default.

## Environment variables

Copy `backend/.env.example` to `backend/.env`. Only `SECRET_KEY` is required.

| Variable | Description |
|---|---|
| `SECRET_KEY` | **Required.** Signs every session token — see the warning below |
| `DATABASE_URL` | SQLite path (default `sqlite+aiosqlite:///./tennis_fantasy.db`) |
| `ENVIRONMENT` | `development` or `production`. Production enforces the `SECRET_KEY` guard; the scrapers also expect `production` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session lifetime (default 10080 = 1 week) |
| `RESEND_API_KEY` | Transactional email. Empty → email is skipped, not an error |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | Web Push. Empty → push is skipped, not an error |

> **`SECRET_KEY` must be your own random value.** Session tokens carry only
> `str(user.id)` and are signed HS256, so anyone who knows the key can mint a
> valid session for any account. The placeholder in `.env.example` is public by
> definition — generate your own:
>
> ```bash
> python -c 'import secrets; print(secrets.token_urlsafe(64))'
> ```
>
> With `ENVIRONMENT=production` the app refuses to start if the key is missing
> or still the placeholder, rather than falling back to it silently.

## Security

- Secrets live only in a local `.env`, which is gitignored and never committed —
  `.env.example` holds placeholder values only.
- Passwords are SHA-256 pre-hashed (so length is unbounded) then bcrypt-hashed.
- CORS is restricted to an explicit origin allowlist, not `*`.
- The frontend ships a strict CSP with no `unsafe-inline` for scripts, so any
  script must be a same-origin file.

Found a vulnerability? Please open a GitHub issue without exploit details, or
use the contact form on the site, rather than posting a working proof of concept.

## Deployment

The frontend builds on Cloudflare Pages from `main`. The backend runs as a Docker
container behind a Cloudflare Tunnel, bound to loopback so it is never exposed
directly. The SQLite database is bind-mounted **as a directory**, never as a single
file — WAL mode writes sibling `-wal`/`-shm` files, and a single-file mount strands
them in the container layer where the next recreate discards them.
