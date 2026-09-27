from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Order


async def count_customers(db: AsyncSession) -> int:
    return await db.scalar(select(func.count(Customer.id))) or 0


async def count_orders(db: AsyncSession) -> int:
    return await db.scalar(select(func.count(Order.id))) or 0


async def total_revenue(db: AsyncSession) -> Decimal:
    return await db.scalar(select(func.coalesce(func.sum(Order.total), 0))) or Decimal("0")
