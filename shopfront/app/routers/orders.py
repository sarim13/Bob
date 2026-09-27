import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.errors import NotFoundError
from app.models import Order
from app.schemas import (
    CheckoutIn,
    OrderCreated,
    OrderDetail,
    OrderLine,
    ShipIn,
    ShipOut,
)
from app.services.audit import record_audit
from app.services.checkout import create_order, reserve_stock
from app.services.shipping import ship_order

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderCreated, status_code=201)
async def place_order(body: CheckoutIn, db: AsyncSession = Depends(get_db)):
    await reserve_stock(db, body.items)
    order = await create_order(db, body.customer_id, body.items, body.coupon_code)
    asyncio.create_task(record_audit(db, "order.placed", order.id))
    return OrderCreated(id=order.id, status=order.status, total=order.total)


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)):
    order = await db.scalar(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    if order is None:
        raise NotFoundError("Order not found")

    return OrderDetail(
        id=order.id,
        status=order.status,
        total=order.total,
        customer_email=order.customer.email,
        items=[
            OrderLine(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in order.items
        ],
    )


@router.post("/{order_id}/ship", response_model=ShipOut)
async def ship(order_id: int, body: ShipIn, db: AsyncSession = Depends(get_db)):
    order = await ship_order(db, order_id, body.carrier)
    return ShipOut(id=order.id, status=order.status)
