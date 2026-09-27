# SD004 BAD – async session.scalar(select(Model)) without eager load, then access relationship
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")


async def get_order_scalar(session: AsyncSession, order_id: int):
    order = await session.scalar(select(Order).where(Order.id == order_id))
    # SD004: accessing relationship 'items' without selectinload
    return order.items
