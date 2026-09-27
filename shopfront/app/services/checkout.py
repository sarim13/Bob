from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CheckoutError
from app.models import Coupon, Customer, Order, OrderItem, Product
from app.schemas import CheckoutItem


async def reserve_stock(db: AsyncSession, items: list[CheckoutItem]) -> None:
    for item in items:
        product = await db.get(Product, item.product_id, with_for_update=True)
        if product is None:
            raise CheckoutError(f"Unknown product {item.product_id}")
        if product.stock < item.quantity:
            raise CheckoutError(f"Not enough stock for {product.sku}")
        product.stock -= item.quantity

    await db.commit()


async def create_order(
    db: AsyncSession,
    customer_id: int,
    items: list[CheckoutItem],
    coupon_code: str | None = None,
) -> Order:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise CheckoutError("Unknown customer")

    product_ids = [item.product_id for item in items]
    result = await db.scalars(select(Product).where(Product.id.in_(product_ids)))
    products = {p.id: p for p in result}

    subtotal = sum(
        (products[item.product_id].price * item.quantity for item in items),
        Decimal("0"),
    )

    discount = Decimal("0")
    if coupon_code:
        coupon = await db.get(Coupon, coupon_code.strip().upper())
        if coupon is None or not coupon.is_valid(datetime.now(timezone.utc)):
            raise CheckoutError("Coupon is not valid")
        discount = (subtotal * coupon.percent_off / 100).quantize(Decimal("0.01"))

    order = Order(customer_id=customer.id, status="placed", total=subtotal - discount)
    order.items = [
        OrderItem(
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=products[item.product_id].price,
        )
        for item in items
    ]
    db.add(order)
    await db.flush()
    return order
