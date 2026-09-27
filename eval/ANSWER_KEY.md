# Shopfront fixture — answer key

**Keep this folder outside the repo Bob can see.** If Bob can read it, the baseline trial is worthless.

- 8 planted bugs (B1–B8) and 2 decoys (D1–D2, correct code that looks suspicious).
- Verified on PostgreSQL 16, FastAPI 0.141, SQLAlchemy 2.0.54 and 2.1.1: on the untouched fixture, **8 bug tests fail and 2 decoy tests pass**. On `reference_fix.diff`, **all 10 pass**. Repeated runs gave identical results, so no test is flaky in this environment.

## Bugs

| ID | File:line | Endpoint | What the user sees | Root cause | Correct fix |
|---|---|---|---|---|---|
| **B1** | `app/db.py:23` | `POST /signup` (and every route relying on it) | Duplicate signup returns **201 Created**, but nothing is saved. The error only shows in server logs. | `get_db` commits after `yield`. On FastAPI ≥ 0.118 that runs **after the response is sent**, so commit failures never reach the client. | Commit explicitly in the route before returning and map `IntegrityError` to 409. Or use `Depends(get_db, scope="function")` (available in the tested FastAPI). **Wrapping `yield` in `async with db.begin():` is NOT a fix.** Verified: it still fails the B1 test. |
| **B2** | `app/db.py:17` + `app/services/inventory.py:13` | `POST /products/{id}/restock` | **500**, yet stock was increased. A client retry restocks twice. | `expire_on_commit` defaults to True; the service commits, then the route reads `product.id` / `product.stock` → expired → lazy refresh → `MissingGreenlet`. | `expire_on_commit=False` on the sessionmaker, and the service should `flush()` instead of commit (route owns the commit). |
| **B3** | `app/routers/orders.py:46` | `GET /orders/{id}` | **500** on every order. | `order.customer` is never eager-loaded (`items` is), so accessing it lazy-loads → `MissingGreenlet`. | Add `selectinload(Order.customer)` (or `joinedload`). |
| **B4** | `app/services/shipping.py:16` | `POST /orders/{id}/ship` | **500**; the order is never shipped. | `db.get()` autobegins a transaction; `async with db.begin():` then raises "A transaction is already begun on this Session". | Drop the `begin()` block; mutate, `flush()`, and let the route commit. |
| **B5** | `app/services/checkout.py:21` (commit) + `:47` (raise) | `POST /orders` with an invalid/expired coupon | **400**, correctly, but stock is permanently decremented with no order. | `reserve_stock()` commits before `create_order()` validates the coupon. Two commits = no atomicity. | Helpers `flush()` only; one commit at the end of the route after everything succeeds. |
| **B6** | `app/routers/admin.py:17` | `GET /admin/dashboard` | **500** every time. It also **leaks a pooled connection** left "idle in transaction", which starves other endpoints (pool size is 2). | `asyncio.gather` runs three queries on one `AsyncSession` concurrently. | Await the queries sequentially, or give each its own session. |
| **B7** | `app/routers/orders.py:30` | `POST /orders` | Checkout returns 201, but **0 of 5 orders get an audit row**. Errors appear only in logs ("session is in 'prepared' state"). | Fire-and-forget `asyncio.create_task` uses the request session while/after it commits and closes. | Await `record_audit` inside the request's transaction before the commit (or give the task its own session and await/queue it properly). |
| **B8** | `app/services/catalog.py:23` (+ `app/routers/products.py:14`) | `GET /products/search` | Works, but after the first call a connection sits **"idle in transaction" forever**. It holds a lock that blocks schema migrations (`ALTER TABLE products` times out) and permanently takes 1 of the 2 pool slots. | A module-level `Catalog(SessionLocal())` shares one session across all requests and never commits or closes. | Create the catalog per request from the request session (`Depends(get_db)`). |

A side effect of stale reads is also possible for B8 (search returning old stock). It depends on garbage collection and appeared on SQLAlchemy 2.1 but not 2.0, so it isn't tested. The idle-transaction / lock symptom is deterministic.

## Decoys (must NOT be changed in behaviour)

| ID | File:line | Why it looks suspicious | Why it's correct |
|---|---|---|---|
| **D1** | `app/services/reports.py:15`, queued from `app/routers/admin.py` via `BackgroundTasks` | Background task doing DB work (looks like B7) | It opens and commits **its own** session; nothing from the request is reused. |
| **D2** | `app/routers/customers.py:27` | `begin_nested()` inside a request session plus a swallowed `IntegrityError` (looks like B4) | A savepoint is legal inside an autobegun transaction; the route commits explicitly **before** returning. Calling it twice is idempotent. |

Scoring a fix attempt: a decoy counts as a **false positive** if the fixer changes it in a way that alters behaviour, or flags it as a bug. Harmless refactors are fine; the D tests will tell you.

## Things worth watching in a Bob run

- **B1 with the `session.begin()` wrapper.** It's the most tempting wrong fix. It looks correct and still loses data.
- **Fixing B2 by only setting `expire_on_commit=False`.** That makes the 500 go away, but the service still commits on its own, which is the same ownership problem as B5.
- **B6/B8 cascading.** On a long-running server, their leaked connections cause *other* endpoints to fail with `QueuePool limit ... timed out`. A fixer who only reads logs may chase the wrong endpoint.
- **Whether it finds B7 and B8 at all.** They don't produce 500s from the endpoint that causes them.

## Running the hidden tests

Needs Postgres (e.g. `docker compose up -d db` in the app folder) and Python 3.11+.

```bash
cd sd-answer-key/tests_hidden
pip install -r requirements.txt -r /path/to/examples/shopfront/requirements.txt
SHOPFRONT_DIR=/path/to/examples/shopfront pytest -v
```

Each test reseeds the database and starts a fresh uvicorn on port 8765 (override with `SHOPFRONT_TEST_PORT`), so tests don't contaminate each other. The whole suite takes about 25 seconds. **The tests drop and recreate the `shopfront` database tables**, so point `DATABASE_URL` at a scratch database.

## Files

- `ANSWER_KEY.md`: this file
- `tests_hidden/`: the 10 tests and the harness
- `reference_fix.diff`: a minimal correct fix (apply with `patch -p1 < reference_fix.diff` from inside the app folder, or read it as a guide). It is one valid fix, not the only one.
