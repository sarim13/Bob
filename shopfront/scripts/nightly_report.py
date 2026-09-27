import argparse
import asyncio
from datetime import date

from app.db import engine
from app.services.reports import build_daily_sales_report


async def run(day: date) -> None:
    await build_daily_sales_report(day)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the daily sales report.")
    parser.add_argument("--day", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    asyncio.run(run(args.day))
    print(f"Report built for {args.day.isoformat()}.")


if __name__ == "__main__":
    main()
