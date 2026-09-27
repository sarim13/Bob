# SD007 BAD – request session passed to background task
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends


async def get_db():
    pass  # simplified dep


async def background_work(session: AsyncSession):
    session.add(object())
    # Missing commit! SD007b also applies here
    await session.flush()


async def route(db: AsyncSession = Depends(get_db)):
    # SD007a: request session passed to create_task
    task = asyncio.create_task(background_work(db))
    return {"ok": True}
