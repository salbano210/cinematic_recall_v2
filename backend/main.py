"""Cinematic Recall v2 — multiplayer pass-and-play movie naming game."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from services.game_board import (
    get_daily_actor_id, get_cached_actor_details, warm_daily_cache,
    board_date_key,
)
from services.tmdb_utils import get_movie_details
from routers.auth import router as auth_router
from routers.matches import router as matches_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Cinematic Recall v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(matches_router)


@app.get("/")
async def read_root():
    # Background warm-up of today's actor so the first match view is instant
    asyncio.create_task(warm_daily_cache())
    return {"message": "Cinematic Recall v2 API"}


@app.get("/daily-actor")
async def daily_actor():
    actor_id = await get_daily_actor_id()
    details = await get_cached_actor_details(actor_id)
    return {
        "actor_id": actor_id,
        "actor_name": details["name"],
        "actor_image": details["profile_url"],
        "match_date": board_date_key(),
    }


@app.get("/movie-details")
async def movie_details(movie_id: int = Query(...)):
    """Synopsis + large poster for the info popup (proxied from TMDb)."""
    try:
        return await get_movie_details(movie_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch movie details")