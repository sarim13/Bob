# SD004 GOOD – session.scalar(select(Model).options(selectinload(...))) should NOT be flagged
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, selectinload, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    items = relationship("Item")


async def get_order_options(session: AsyncSession, order_id: int):
    order = await session.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    return order.items  # safe: selectinload in query chain
