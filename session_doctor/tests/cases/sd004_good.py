# SD004 GOOD – eager load specified
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, DeclarativeBase, selectinload


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item", lazy="selectin")


async def get_order(session: AsyncSession, order_id: int):
    order = await session.get(Order, order_id)
    # OK: lazy="selectin" is safe
    return order.items
