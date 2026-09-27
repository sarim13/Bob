# SD001 GOOD – commit in route, not in dependency
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from fastapi import Depends

AsyncSessionLocal = async_sessionmaker(expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session  # no commit here


async def route(db: AsyncSession = Depends(get_db)):
    db.add(object())
    await db.commit()  # committed by the owner (route)
    return {"ok": True}
