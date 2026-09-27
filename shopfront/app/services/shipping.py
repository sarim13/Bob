from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import InvalidStateError, NotFoundError
from app.models import Order, Shipment


async def ship_order(db: AsyncSession, order_id: int, carrier: str) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.status != "placed":
        raise InvalidStateError(f"Order {order_id} is {order.status}")

    async with db.begin():
        order.status = "shipped"
        order.shipped_at = datetime.now(timezone.utc)
        db.add(Shipment(order_id=order.id, carrier=carrier))

    return order
