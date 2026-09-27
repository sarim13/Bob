import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db import SessionLocal, engine
from app.models import Base, Coupon, Customer, Order, OrderItem, Product

PRODUCTS = [
    ("MUG-CER-01", "Ceramic Mug", Decimal("14.00"), 40),
    ("MUG-TRV-01", "Travel Mug", Decimal("22.50"), 25),
    ("TEE-BLK-M", "Black Tee (M)", Decimal("19.00"), 60),
    ("TEE-WHT-M", "White Tee (M)", Decimal("19.00"), 55),
    ("NBK-A5-01", "A5 Notebook", Decimal("9.50"), 120),
    ("STK-PACK", "Sticker Pack", Decimal("4.00"), 300),
]

CUSTOMERS = [
    ("ayesha@example.com", "Ayesha Khan"),
    ("daniel@example.com", "Daniel Reyes"),
    ("mei@example.com", "Mei Tanaka"),
]


async def seed(reset: bool) -> None:
    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        async with session.begin():
            products = [
                Product(sku=sku, name=name, price=price, stock=stock)
                for sku, name, price, stock in PRODUCTS
            ]
            customers = [Customer(email=email, name=name) for email, name in CUSTOMERS]
            session.add_all(products + customers)
            session.add_all(
                [
                    Coupon(code="WELCOME10", percent_off=10, active=True),
                    Coupon(
                        code="SUMMER25",
                        percent_off=25,
                        active=True,
                        expires_at=now - timedelta(days=30),
                    ),
                ]
            )
            await session.flush()

            mug, tee = products[0], products[2]
            first = Order(customer_id=customers[0].id, status="placed", total=Decimal("47.00"))
            first.items = [
                OrderItem(product_id=mug.id, quantity=2, unit_price=mug.price),
                OrderItem(product_id=tee.id, quantity=1, unit_price=tee.price),
            ]
            second = Order(
                customer_id=customers[1].id,
                status="shipped",
                total=Decimal("14.00"),
                shipped_at=now - timedelta(days=2),
            )
            second.items = [OrderItem(product_id=mug.id, quantity=1, unit_price=mug.price)]
            session.add_all([first, second])

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create tables and load sample data.")
    parser.add_argument("--reset", action="store_true", help="drop existing tables first")
    args = parser.parse_args()
    asyncio.run(seed(args.reset))
    print("Seed data loaded.")


if __name__ == "__main__":
    main()
