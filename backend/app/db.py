"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """Base class for ORM models."""


engine = create_async_engine(
    settings.resolve_database_url(),
    echo=False,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create database tables. Safe to run on every startup."""

    from sqlalchemy import text

    from . import models  # noqa: F401 — ensure models are imported before create_all

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight in-place migration: add columns introduced after the
        # initial schema. ``create_all`` only creates missing tables, it never
        # alters existing ones, so on pre-existing databases we need to ALTER
        # to pick up new columns.
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        columns = {row[1] for row in result.fetchall()}
        if "attachments" not in columns:
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN attachments TEXT")
            )
        if "variant" not in columns:
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN variant INTEGER")
            )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an ``AsyncSession``."""

    async with SessionLocal() as session:
        yield session
