"""SQLAlchemy models: users, matches, match_players, turns."""
import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[int] = mapped_column(Integer)          # TMDb actor for the board
    match_date: Mapped[str] = mapped_column(String(10))     # YYYY-MM-DD (Eastern) — board key
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | finished
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    invite_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    players: Mapped[list["MatchPlayer"]] = relationship(back_populates="match", cascade="all, delete-orphan")
    state: Mapped["MatchState"] = relationship(back_populates="match", uselist=False)
    turns: Mapped[list["Turn"]] = relationship(back_populates="match")


class MatchPlayer(Base):
    __tablename__ = "match_players"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    turn_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | resigned
    timeouts_in_a_row: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    match: Mapped[Match] = relationship(back_populates="players")
    user: Mapped[User] = relationship()


class Turn(Base):
    """One player turn: from assignment to guess/miss/resign."""
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)  # named | miss | timeout | resign
    guess_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # timer starts here
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    match: Mapped[Match] = relationship(back_populates="turns")


class MatchState(Base):
    """Authoritative live state: whose turn, timer, and public named claims."""
    __tablename__ = "match_state"

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    current_turn_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("turns.id"), nullable=True)
    named_ranks: Mapped[dict] = mapped_column(JSON, default=dict)
    # named_ranks: { "12": {"user_id": ..., "title": ..., "year": ..., "percentage": ..., "named_at": ...} }
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    match: Mapped[Match] = relationship(back_populates="state")
    current_turn: Mapped[Turn | None] = relationship()
