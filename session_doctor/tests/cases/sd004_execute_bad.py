# SD004 BAD – session.execute(select(Model)), extract with scalar_one(), access relationship
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")


async def get_order_execute(session: AsyncSession, order_id: int):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one()
    # SD004: accessing relationship 'items' without selectinload
    return order.items
