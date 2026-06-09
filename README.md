# Upset Alert 🎾

A tennis fantasy league app. Make predictions on tournament draws, compete in groups with friends, and track scores as results come in.

## Features

- **Live bracket draws** — tournament draws scraped from Wikipedia and updated in real-time via EventStreams
- **Predictions** — pick a winner for every match before the draw closes; picks lock automatically at the first scheduled match
- **Scoring** — four modes: Classic (doubling points), ATP/WTA Points Mirror, Upset Bonus, or Custom
- **Groups** — create or join a league; the leaderboard for any group is filtered to members who completed the full bracket for that tournament
- **Auto-discovery** — new ATP/WTA tournaments are discovered and added automatically from season pages
- **Rankings** — draw seedings sourced from Jeff Sackmann's tennis rankings data

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.9+, FastAPI, SQLAlchemy (async), SQLite |
| Frontend | React 18, Vite, TanStack Query v5 |
| Data | Wikipedia API, ATP/WTA EventStreams, GitHub CSV rankings |

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── routers/       # FastAPI route handlers
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # Scraper, scoring, rankings, scheduler
│   │   └── main.py
│   └── requirements.txt
└── frontend/
    └── src/
        ├── api/           # Axios API clients
        ├── components/    # BracketView, Navbar
        ├── pages/         # Tournaments, TournamentDraw, Leagues, LeagueDetail
        └── store/         # Auth state
```

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SECRET_KEY
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend proxies API requests to `http://localhost:8000` via Vite config.

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and set:

| Variable | Description |
|---|---|
| `SECRET_KEY` | JWT signing secret |
| `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///./tennis_fantasy.db`) |
