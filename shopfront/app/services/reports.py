from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.models import DailyReport, Order


async def build_daily_sales_report(day: date) -> None:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    async with SessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                    .where(Order.created_at >= start, Order.created_at < end)
                )
            ).one()
            order_count, revenue = row

            stmt = insert(DailyReport).values(
                day=day, order_count=order_count, revenue=Decimal(revenue)
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[DailyReport.day],
                set_={"order_count": order_count, "revenue": Decimal(revenue)},
            )
            await session.execute(stmt)
