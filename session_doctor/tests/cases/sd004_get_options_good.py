# SD004 GOOD – session.get with options=[selectinload(...)] should NOT be flagged
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, selectinload, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")


async def get_order_with_options(session: AsyncSession, order_id: int):
    order = await session.get(Order, order_id, options=[selectinload(Order.items)])
    return order.items  # safe: loaded via options=
