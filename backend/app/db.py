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

    from . import models  # noqa: F401 — ensure models are imported before create_all

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an ``AsyncSession``."""

    async with SessionLocal() as session:
        yield session
