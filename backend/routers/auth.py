"""Auth endpoints: register, login, me, crew."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, MatchPlayer, Match
from auth import hash_password, verify_password, create_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: str
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str
    user: dict


@router.post("/register", response_model=TokenOut)
async def register(data: RegisterIn, db: AsyncSession = Depends(get_db)):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(data.display_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Display name must be at least 2 characters")

    existing = await db.execute(select(User).where(User.email == data.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(
        email=data.email.lower(),
        display_name=data.display_name.strip(),
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenOut(
        token=create_token(user.id),
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
    )


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    return TokenOut(
        token=create_token(user.id),
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


@router.get("/crew")
async def get_crew(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Everyone I've ever played with — used to auto-populate new matches."""
    result = await db.execute(
        select(User)
        .join(MatchPlayer, MatchPlayer.user_id == User.id)
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(Match.created_by == user.id)
        .where(User.id != user.id)
        .distinct()
    )
    crew = result.scalars().all()
    return [{"id": u.id, "display_name": u.display_name, "email": u.email} for u in crew]
