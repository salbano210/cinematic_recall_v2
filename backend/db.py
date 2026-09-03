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
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg rejects `sslmode`/`channel_binding` as connect kwargs — strip them
    # from the query string; SSL is configured via connect_args below.
    for param in ("sslmode=require", "channel_binding=require"):
        url = url.replace(f"&{param}", "").replace(f"?{param}", "")
    return url


DATABASE_URL = _database_url()

# Neon requires SSL; local SQLite does not
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine_kwargs = {"connect_args": connect_args}
else:
    import ssl
    ssl_ctx = ssl.create_default_context()
    engine_kwargs = {"connect_args": {"ssl": ssl_ctx}, "pool_pre_ping": True}

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Create tables on startup (Alembic can replace this later if needed)."""
    import models  # noqa: F401 — register models with Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
