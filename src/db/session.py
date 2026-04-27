from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@dataclass(slots=True)
class DatabaseManager:
    engine: AsyncEngine
    session_maker: async_sessionmaker[AsyncSession]


def create_database_manager(database_url: str) -> DatabaseManager:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return DatabaseManager(engine=engine, session_maker=session_maker)


async def ping_database(database: DatabaseManager) -> None:
    async with database.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
