from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
# Import models in dependency order so SQLAlchemy can resolve relationships
import app.models.user  # noqa: F401
import app.models.prediction  # noqa: F401
import app.models.league  # noqa: F401
import app.models.tournament  # noqa: F401
from app.services.scheduler import start_scheduler, stop_scheduler
from app.routers import auth, discovery, leagues, predictions, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Tennis Fantasy League", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tournaments.router)
app.include_router(discovery.router)
app.include_router(leagues.router)
app.include_router(predictions.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
