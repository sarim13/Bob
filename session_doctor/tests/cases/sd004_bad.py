# SD004 BAD – async session loads model then accesses relationship without eager load
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")


async def get_order(session: AsyncSession, order_id: int):
    order = await session.get(Order, order_id)
    # SD004: accessing relationship 'items' without selectinload
    return order.items
