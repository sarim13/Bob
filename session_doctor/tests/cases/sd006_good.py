# SD006 GOOD – each coroutine gets its own session
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

AsyncSessionLocal = async_sessionmaker(expire_on_commit=False)


async def write_a():
    async with AsyncSessionLocal() as session:
        session.add(object())
        await session.commit()


async def write_b():
    async with AsyncSessionLocal() as session:
        session.add(object())
        await session.commit()


async def route():
    await asyncio.gather(write_a(), write_b())
