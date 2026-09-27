# SD005 BAD – begin() called after a query (autobegin already active)
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_and_update(session: AsyncSession, user_id: int):
    user = await session.get(object, user_id)  # autobegin triggered here
    async with session.begin():  # SD005: redundant begin after autobegin
        user.active = False
