# SD005 GOOD – begin() is the very first operation on the session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

AsyncSessionLocal = async_sessionmaker()


async def run_transaction():
    async with AsyncSessionLocal() as session:
        async with session.begin():  # OK: first op is begin
            session.add(object())
