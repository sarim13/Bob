# SD004 BAD – eager-loads 'items' but reads unloaded relationship 'customer'
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, selectinload, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")
    customer = relationship("Customer")


async def get_order(session: AsyncSession, order_id: int):
    order = await session.scalar(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    # SD004: 'customer' was never eager-loaded
    return order.customer.email, order.items
