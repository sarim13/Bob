import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/shopfront",
)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=2,
    max_overflow=0,
    pool_timeout=3,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession)


async def get_db():
    async with SessionLocal() as db:
        yield db
        await db.commit()
