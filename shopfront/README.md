# Shopfront API

A small storefront backend: customers, a product catalog, checkout with coupons, order tracking and shipping, plus a couple of admin endpoints.

Built with FastAPI, SQLAlchemy 2.0 (async) and PostgreSQL.

## Running locally

```bash
docker compose up -d db
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed --reset
uvicorn app.main:app --reload
```

Interactive docs are at http://localhost:8000/docs.

The database URL defaults to `postgresql+asyncpg://postgres:postgres@localhost:5432/shopfront` and can be overridden with `DATABASE_URL`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/signup` | Register a customer |
| POST | `/customers/{id}/newsletter` | Opt a customer in to the newsletter |
| GET | `/products/search?q=` | Search products by name |
| POST | `/products/{id}/restock` | Add stock to a product |
| POST | `/orders` | Place an order (optional `coupon_code`) |
| GET | `/orders/{id}` | Order details with line items |
| POST | `/orders/{id}/ship` | Mark an order as shipped |
| GET | `/admin/dashboard` | Customer, order and revenue totals |
| POST | `/admin/reports/daily` | Queue the daily sales report |

## Sample data

`python -m scripts.seed --reset` loads three customers, six products, two coupons (`WELCOME10` is active, `SUMMER25` has expired) and two orders.

The daily report can also be built from the command line:

```bash
python -m scripts.nightly_report --day 2026-09-25
```
