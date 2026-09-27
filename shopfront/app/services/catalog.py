from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Product


class Catalog:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(self, query: str, limit: int = 20) -> list[Product]:
        stmt = (
            select(Product)
            .where(Product.name.ilike(f"%{query}%"))
            .order_by(Product.name)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result)


catalog = Catalog(SessionLocal())
