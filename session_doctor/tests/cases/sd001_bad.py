# SD001 BAD – commit-after-yield in a session dependency
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from fastapi import Depends

AsyncSessionLocal = async_sessionmaker(expire_on_commit=True)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()  # SD001: commit after yield


async def route(db: AsyncSession = Depends(get_db)):
    db.add(object())
    return {"ok": True}
