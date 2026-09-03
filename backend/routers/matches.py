"""Match lifecycle & turn engine: create, join, start-turn, guess, resign, state.

Timer rules (server-authoritative):
- A turn is ASSIGNED (email sent, no timer). It never expires while unstarted.
- When the player calls /start-turn, the server stamps started_at. The player
  then has TURN_SECONDS to submit a guess.
- Expiry is enforced lazily: on any state fetch or action, an expired started
  turn is marked as a timeout and the turn advances.
"""
import os
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, Match, MatchPlayer, Turn, MatchState
from auth import get_current_user
from services.game_board import get_ranked_board, get_cached_actor_details, find_title_match, board_date_key
from services.emailer import email_turn_assigned, email_invite

router = APIRouter(prefix="/matches", tags=["matches"])

TURN_SECONDS = 120          # 2 minutes, from the player starting their turn
TIMEOUTS_BEFORE_AUTO_RESIGN = 3

# Base URL for email deep links (the frontend site)
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")


def _match_url(match_id: str) -> str | None:
    return f"{FRONTEND_URL}/?match={match_id}" if FRONTEND_URL else None


async def _notify_turn_assigned(db: AsyncSession, match: Match, players: list[MatchPlayer],
                                namer_name: str | None = None, namer_movie: str | None = None):
    """Email the player whose turn was just assigned (if the turn exists)."""
    state = await _load_state(db, match)
    if not state.current_turn_id:
        return
    turn = (await db.execute(select(Turn).where(Turn.id == state.current_turn_id))).scalar_one_or_none()
    if not turn:
        return
    player = next((p for p in players if p.user_id == turn.user_id), None)
    if not player:
        return
    target = await db.get(User, turn.user_id)
    if not target:
        return
    actor_name = (await get_cached_actor_details(match.actor_id))["name"]
    email_turn_assigned(
        target.email, target.display_name, actor_name,
        namer_name, namer_movie, _match_url(match.id),
    )


class CreateMatchIn(BaseModel):
    crew_user_ids: list[str] = []


class GuessIn(BaseModel):
    guess: str


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

async def _load_match(db: AsyncSession, match_id: str) -> Match:
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


async def _load_players(db: AsyncSession, match_id: str) -> list[MatchPlayer]:
    result = await db.execute(select(MatchPlayer).where(MatchPlayer.match_id == match_id))
    players = list(result.scalars().all())
    players.sort(key=lambda p: p.turn_order)
    return players


async def _load_state(db: AsyncSession, match: Match) -> MatchState:
    result = await db.execute(select(MatchState).where(MatchState.match_id == match.id))
    state = result.scalar_one_or_none()
    if not state:
        state = MatchState(match_id=match.id, named_ranks={})
        db.add(state)
        await db.flush()
        await db.refresh(state)
    return state


def _next_active_player(players: list[MatchPlayer], after_order: int) -> MatchPlayer | None:
    """Next active player in turn order after the given order (wrapping)."""
    active = [p for p in players if p.status == "active"]
    if not active:
        return None
    after = [p for p in active if p.turn_order > after_order]
    return after[0] if after else active[0]  # wrap around


def _turn_seconds_left(turn: Turn) -> int | None:
    """Seconds remaining on a STARTED turn. None = not started (no timer)."""
    if turn.started_at is None:
        return None
    elapsed = (datetime.utcnow() - turn.started_at).total_seconds()
    return max(0, TURN_SECONDS - int(elapsed))


async def _assign_next_turn(db: AsyncSession, match: Match, state: MatchState,
                            players: list[MatchPlayer], after_order: int) -> bool:
    """Assign a turn to the next active player. Returns False if the match
    should finish (fewer than 2 active players remain)."""
    active = [p for p in players if p.status == "active"]
    if len(active) <= 1:
        match.status = "finished"
        state.current_turn_id = None
        return False

    nxt = _next_active_player(players, after_order)
    turn = Turn(match_id=match.id, user_id=nxt.user_id)
    db.add(turn)
    await db.flush()
    state.current_turn_id = turn.id
    return True


async def _expire_if_needed(db: AsyncSession, match: Match, state: MatchState,
                            players: list[MatchPlayer]) -> None:
    """Lazy timeout: if the current turn was started and the clock ran out,
    record a timeout miss and advance. Called on every state fetch / action."""
    if match.status != "active" or not state.current_turn_id:
        return

    result = await db.execute(select(Turn).where(Turn.id == state.current_turn_id))
    turn = result.scalar_one_or_none()
    if not turn or turn.outcome is not None:
        return
    if turn.started_at is None:
        return  # unstarted turns never expire (that's the design)

    seconds_left = _turn_seconds_left(turn)
    if seconds_left is None or seconds_left > 0:
        return

    # Expired: record timeout, advance
    turn.outcome = "timeout"
    turn.ended_at = datetime.utcnow()

    player = next((p for p in players if p.user_id == turn.user_id), None)
    if player:
        player.timeouts_in_a_row = (player.timeouts_in_a_row or 0) + 1
        if player.timeouts_in_a_row >= TIMEOUTS_BEFORE_AUTO_RESIGN:
            player.status = "resigned"
        after_order = player.turn_order
    else:
        after_order = 0

    await _assign_next_turn(db, match, state, players, after_order=after_order)


async def _finish_turn_and_advance(db: AsyncSession, match: Match, state: MatchState,
                                   players: list[MatchPlayer], turn: Turn,
                                   outcome: str, guess_text: str | None = None,
                                   matched_rank: int | None = None) -> None:
    """Close out the current turn with an outcome and move to the next player."""
    turn.outcome = outcome
    turn.guess_text = guess_text
    turn.matched_rank = matched_rank
    turn.ended_at = datetime.utcnow()

    player = next((p for p in players if p.user_id == turn.user_id), None)
    if outcome == "timeout" and player:
        player.timeouts_in_a_row = (player.timeouts_in_a_row or 0) + 1
        if player.timeouts_in_a_row >= TIMEOUTS_BEFORE_AUTO_RESIGN:
            player.status = "resigned"
    elif outcome == "named" and player:
        player.timeouts_in_a_row = 0

    await _assign_next_turn(db, match, state, players, after_order=player.turn_order if player else 0)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@router.post("")
async def create_match(data: CreateMatchIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Start a match for today's daily actor with me + my crew."""
    from services.game_board import get_daily_actor_id
    actor_id = await get_daily_actor_id()

    # Resolve crew: creator + listed user ids (must be existing users)
    member_ids = [user.id]
    for uid in dict.fromkeys(data.crew_user_ids):  # dedupe, keep order
        if uid != user.id:
            result = await db.execute(select(User).where(User.id == uid))
            if result.scalar_one_or_none():
                member_ids.append(uid)

    if len(member_ids) < 2:
        raise HTTPException(status_code=400, detail="A match needs at least one opponent")

    match = Match(
        actor_id=actor_id,
        match_date=board_date_key(),
        created_by=user.id,
        invite_token=secrets.token_urlsafe(24),
    )
    db.add(match)
    await db.flush()

    for idx, uid in enumerate(member_ids):
        db.add(MatchPlayer(match_id=match.id, user_id=uid, turn_order=idx))

    state = MatchState(match_id=match.id, named_ranks={})
    db.add(state)
    await db.flush()

    # Assign the first turn (creator starts)
    first = await db.execute(select(MatchPlayer).where(
        MatchPlayer.match_id == match.id, MatchPlayer.user_id == user.id))
    first_player = first.scalar_one()
    turn = Turn(match_id=match.id, user_id=first_player.user_id)
    db.add(turn)
    await db.flush()
    state.current_turn_id = turn.id
    await db.commit()

    # Email the rest of the crew: creator started a match (also serves as the
    # "new game started" heads-up for existing crew members).
    actor_name = (await get_cached_actor_details(actor_id))["name"]
    players = await _load_players(db, match.id)
    for p in players:
        if p.user_id == user.id:
            continue
        u = await db.get(User, p.user_id)
        if u:
            email_invite(u.email, user.display_name, _match_url(match.id) or f"{FRONTEND_URL}")

    return {"match_id": match.id, "invite_token": match.invite_token,
            "actor_id": actor_id, "player_count": len(member_ids)}


@router.post("/join/{invite_token}")
async def join_match(invite_token: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """Join a match via its invite link (first-timers register first, then hit this)."""
    result = await db.execute(select(Match).where(Match.invite_token == invite_token))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    if match.status != "active":
        raise HTTPException(status_code=400, detail="This match has already finished")

    players = await _load_players(db, match.id)
    if any(p.user_id == user.id for p in players):
        return {"match_id": match.id, "already_member": True}

    max_order = max((p.turn_order for p in players), default=-1)
    db.add(MatchPlayer(match_id=match.id, user_id=user.id, turn_order=max_order + 1))
    await db.commit()
    return {"match_id": match.id, "already_member": False}


@router.get("/{match_id}/state")
async def get_match_state(match_id: str, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Full match state: board with public claims, players, current turn.
    Unclaimed titles are NEVER sent — the server holds them."""
    match = await _load_match(db, match_id)
    players = await _load_players(db, match.id)
    if not any(p.user_id == user.id for p in players):
        raise HTTPException(status_code=403, detail="You are not in this match")

    state = await _load_state(db, match)
    await _expire_if_needed(db, match, state, players)

    # Current turn info
    current = None
    if state.current_turn_id:
        result = await db.execute(select(Turn).where(Turn.id == state.current_turn_id))
        turn = result.scalar_one_or_none()
        if turn:
            seconds_left = _turn_seconds_left(turn)
            current = {
                "user_id": turn.user_id,
                "turn_id": turn.id,
                "started": turn.started_at is not None,
                "seconds_left": seconds_left,   # None while unstarted
                "your_turn": turn.user_id == user.id,
            }

    # Public board claims: rank -> who named it + movie info
    named = state.named_ranks or {}
    actor_name = (await get_cached_actor_details(match.actor_id))["name"]
    user_map = {}
    if players:
        ids = [p.user_id for p in players]
        result = await db.execute(select(User).where(User.id.in_(ids)))
        user_map = {u.id: u.display_name for u in result.scalars().all()}

    board_claims = {}
    for rank_str, claim in named.items():
        board_claims[rank_str] = {
            "by": user_map.get(claim.get("user_id"), "?"),
            "user_id": claim.get("user_id"),
            "title": claim.get("title"),
            "year": claim.get("year"),
            "percentage": claim.get("percentage"),
        }

    players_out = [{
        "user_id": p.user_id,
        "display_name": user_map.get(p.user_id, "?"),
        "status": p.status,
        "turn_order": p.turn_order,
        "named_count": sum(1 for c in named.values() if c.get("user_id") == p.user_id),
        "is_me": p.user_id == user.id,
    } for p in players]

    # Only compute total when the match is finished (avoid slow TMDb calls in
    # the hot path while playing) — actually the board total is needed for the
    # grid; fetch it (cached per day, so cheap after first call).
    board = await get_ranked_board(match.actor_id)

    return {
        "match": {
            "id": match.id,
            "status": match.status,
            "match_date": match.match_date,
            "created_by": match.created_by,
        },
        "actor_name": actor_name,
        "total_movies": len(board),
        "players": players_out,
        "current_turn": current,
        "board": board_claims,
    }


@router.post("/{match_id}/start-turn")
async def start_turn(match_id: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """Start the 2-minute clock on MY assigned turn. Idempotent."""
    match = await _load_match(db, match_id)
    if match.status != "active":
        raise HTTPException(status_code=400, detail="Match is finished")
    state = await _load_state(db, match)
    players = await _load_players(db, match.id)
    await _expire_if_needed(db, match, state, players)

    if not state.current_turn_id:
        raise HTTPException(status_code=400, detail="No turn to start")
    result = await db.execute(select(Turn).where(Turn.id == state.current_turn_id))
    turn = result.scalar_one_or_none()
    if not turn or turn.user_id != user.id:
        raise HTTPException(status_code=403, detail="It's not your turn")
    if turn.outcome is not None:
        raise HTTPException(status_code=400, detail="This turn already ended")

    if turn.started_at is None:
        turn.started_at = datetime.utcnow()
        await db.commit()

    return {"started": True, "seconds_left": TURN_SECONDS}


@router.post("/{match_id}/guess")
async def submit_guess(match_id: str, data: GuessIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Submit a guess on my turn. Server enforces the 2-minute window."""
    match = await _load_match(db, match_id)
    if match.status != "active":
        raise HTTPException(status_code=400, detail="Match is finished")

    players = await _load_players(db, match.id)
    state = await _load_state(db, match)
    await _expire_if_needed(db, match, state, players)

    if not state.current_turn_id:
        raise HTTPException(status_code=400, detail="No active turn")
    result = await db.execute(select(Turn).where(Turn.id == state.current_turn_id))
    turn = result.scalar_one_or_none()
    if not turn or turn.user_id != user.id:
        raise HTTPException(status_code=403, detail="It's not your turn")
    if turn.outcome is not None:
        raise HTTPException(status_code=400, detail="This turn is already over")
    if turn.started_at is None:
        raise HTTPException(status_code=400, detail="Start your turn first")

    seconds_left = _turn_seconds_left(turn)
    if seconds_left is not None and seconds_left <= 0:
        await _finish_turn_and_advance(db, match, state, players, turn, outcome="timeout",
                                       guess_text=data.guess)
        await db.commit()
        await _notify_turn_assigned(db, match, players)
        raise HTTPException(status_code=408, detail="Time's up! Your turn expired.")

    # Validate the guess against the daily board, excluding claimed ranks
    board = await get_ranked_board(match.actor_id)
    named = state.named_ranks or {}
    claimed_ranks = {int(r) for r in named.keys()}
    unused = [m["title"].lower() for m in board if m["rank"] not in claimed_ranks]

    guess = data.guess.strip().lower()
    if not guess:
        raise HTTPException(status_code=400, detail="Type a movie title")
    if len(guess) < 3 and guess not in unused:
        raise HTTPException(status_code=400, detail="Please type more of the movie title")

    matched_title = find_title_match(guess, unused)
    if not matched_title:
        return {"correct": False, "message": "Movie not recognized — keep trying, the clock is running!"}

    movie_entry = next(m for m in board if m["title"].lower() == matched_title)
    rank = str(movie_entry["rank"])

    # Claim it: public, permanent, credited to me
    named[rank] = {
        "user_id": user.id,
        "title": movie_entry["title"],
        "year": movie_entry.get("year"),
        "percentage": movie_entry["percentage"],
        "movie_id": movie_entry["id"],
        "poster_url": movie_entry.get("poster_url"),
        }
    state.named_ranks = named  # reassign so SQLAlchemy detects the JSON change

    await _finish_turn_and_advance(db, match, state, players, turn,
                                   outcome="named", guess_text=data.guess,
                                   matched_rank=movie_entry["rank"])
    await db.commit()
    await _notify_turn_assigned(db, match, players,
                                namer_name=user.display_name, namer_movie=movie_entry["title"])

    return {"correct": True, "rank": movie_entry["rank"], "title": movie_entry["title"]}


@router.post("/{match_id}/resign")
async def resign(match_id: str, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    """Resign: removed from rotation. If it was my turn, the turn passes on."""
    match = await _load_match(db, match_id)
    if match.status != "active":
        raise HTTPException(status_code=400, detail="Match is finished")

    players = await _load_players(db, match.id)
    me = next((p for p in players if p.user_id == user.id), None)
    if not me:
        raise HTTPException(status_code=403, detail="You are not in this match")

    state = await _load_state(db, match)
    was_my_turn = False
    if state.current_turn_id:
        result = await db.execute(select(Turn).where(Turn.id == state.current_turn_id))
        turn = result.scalar_one_or_none()
        if turn and turn.user_id == user.id and turn.outcome is None:
            was_my_turn = True
            turn.outcome = "resign"
            turn.ended_at = datetime.utcnow()

    me.status = "resigned"

    if was_my_turn:
        await _assign_next_turn(db, match, state, players, after_order=me.turn_order)
    elif len([p for p in players if p.status == "active"]) <= 1:
        match.status = "finished"
        state.current_turn_id = None

    await db.commit()
    return {"resigned": True, "match_status": match.status}


@router.get("")
async def my_matches(user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """My matches with pending-turn flags for the notification badge."""
    result = await db.execute(
        select(MatchPlayer, Match)
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(MatchPlayer.user_id == user.id)
        .order_by(Match.created_at.desc())
    )
    rows = result.all()

    out = []
    for mp, match in rows:
        # whose turn is it (if match active)?
        your_turn = False
        awaiting_start = False
        if match.status == "active":
            st = await _load_state(db, match)
            if st.current_turn_id:
                t = (await db.execute(select(Turn).where(Turn.id == st.current_turn_id))).scalar_one_or_none()
                if t and t.user_id == user.id and t.outcome is None:
                    your_turn = True
                    awaiting_start = t.started_at is None
        out.append({
            "match_id": match.id,
            "status": match.status,
            "match_date": match.match_date,
            "your_turn": your_turn,
            "awaiting_start": awaiting_start,
        })
    return out


