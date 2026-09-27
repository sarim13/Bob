# SD007 GOOD – background task opens its own session and commits
import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

AsyncSessionLocal = async_sessionmaker(expire_on_commit=False)


async def background_work():
    async with AsyncSessionLocal() as session:
        session.add(object())
        await session.commit()  # commits its own session


async def route():
    task = asyncio.create_task(background_work())  # no request session passed
    return {"ok": True}
