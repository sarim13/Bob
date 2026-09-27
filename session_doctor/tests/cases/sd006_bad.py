# SD006 BAD – same session shared across asyncio.gather coroutines
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession


async def write_a(session: AsyncSession):
    session.add(object())
    await session.flush()


async def write_b(session: AsyncSession):
    session.add(object())
    await session.flush()


async def route(session: AsyncSession):
    # SD006: same session passed to two concurrent coroutines
    await asyncio.gather(write_a(session), write_b(session))
    await session.commit()
