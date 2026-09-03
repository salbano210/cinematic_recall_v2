"""Database engine & session. Postgres (Neon) in prod, SQLite for local dev."""
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        # Local dev default: SQLite file (prod always sets DATABASE_URL to Neon)
        return "sqlite+aiosqlite:///./cr_v2.db"
    if url.startswith("postgres://"):
        # Neon/Heroku-style URLs need the asyncpg driver
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = _database_url()

# Neon requires SSL; local SQLite does not
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_async_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Create tables on startup (Alembic can replace this later if needed)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
