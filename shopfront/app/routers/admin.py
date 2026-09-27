import asyncio
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import DashboardOut, ReportRequest
from app.services.reports import build_daily_sales_report
from app.services.stats import count_customers, count_orders, total_revenue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(db: AsyncSession = Depends(get_db)):
    customers, orders, revenue = await asyncio.gather(
        count_customers(db),
        count_orders(db),
        total_revenue(db),
    )
    return DashboardOut(customers=customers, orders=orders, revenue=revenue)


@router.post("/reports/daily", status_code=202)
async def queue_daily_report(body: ReportRequest, background_tasks: BackgroundTasks):
    day = body.day or date.today()
    background_tasks.add_task(build_daily_sales_report, day)
    return {"queued": day.isoformat()}
