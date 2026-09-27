"""One test per planted bug (B1-B8) plus guards for the two decoys (D1-D2).

On the untouched fixture every B test fails and every D test passes.
A correct fix turns a B test green without turning any D test red.
"""

import asyncio
import time
from datetime import datetime, timezone

import asyncpg
import pytest

from conftest import PG_DSN, db_exec, db_val


# ---------------------------------------------------------------- B1
def test_b1_duplicate_signup_is_not_reported_as_success(server):
    first = server.post("/signup", json={"email": "sam@example.com", "name": "Sam"})
    assert first.status_code == 201
    time.sleep(0.5)
    assert db_val("SELECT count(*) FROM customers WHERE email = $1", "sam@example.com") == 1

    second = server.post("/signup", json={"email": "sam@example.com", "name": "Sam Again"})
    time.sleep(0.5)
    assert db_val("SELECT count(*) FROM customers WHERE email = $1", "sam@example.com") == 1
    assert second.status_code != 201, (
        "client was told the signup succeeded, but the commit failed after the "
        "response was sent and nothing was saved"
    )


# ---------------------------------------------------------------- B2
def test_b2_restock_returns_new_stock(server):
    before = db_val("SELECT stock FROM products WHERE id = 1")
    resp = server.post("/products/1/restock", json={"quantity": 5})
    after = db_val("SELECT stock FROM products WHERE id = 1")

    assert after == before + 5
    assert resp.status_code == 200, (
        f"restock was committed (stock {before} -> {after}) but the request "
        f"failed with {resp.status_code}; a client retry would restock twice"
    )
    assert resp.json() == {"id": 1, "stock": before + 5}


# ---------------------------------------------------------------- B3
def test_b3_order_detail_includes_customer_email(server):
    resp = server.get("/orders/1")
    assert resp.status_code == 200, f"GET /orders/1 failed with {resp.status_code}"
    body = resp.json()
    assert body["customer_email"] == "ayesha@example.com"
    assert len(body["items"]) == 2


# ---------------------------------------------------------------- B4
def test_b4_ship_placed_order(server):
    resp = server.post("/orders/1/ship", json={"carrier": "dhl"})
    assert resp.status_code == 200, f"shipping failed with {resp.status_code}"
    assert resp.json()["status"] == "shipped"
    time.sleep(0.3)
    assert db_val("SELECT status FROM orders WHERE id = 1") == "shipped"
    assert db_val("SELECT count(*) FROM shipments WHERE order_id = 1") == 1


# ---------------------------------------------------------------- B5
def test_b5_failed_checkout_does_not_consume_stock(server):
    before = db_val("SELECT stock FROM products WHERE id = 2")
    resp = server.post(
        "/orders",
        json={
            "customer_id": 1,
            "items": [{"product_id": 2, "quantity": 2}],
            "coupon_code": "SUMMER25",
        },
    )
    assert resp.status_code == 400
    time.sleep(0.3)
    after = db_val("SELECT stock FROM products WHERE id = 2")
    assert after == before, (
        f"checkout was rejected but stock went {before} -> {after} with no order created"
    )


# ---------------------------------------------------------------- B6
def test_b6_dashboard_totals(server):
    for _ in range(3):
        resp = server.get("/admin/dashboard")
        assert resp.status_code == 200, f"dashboard failed with {resp.status_code}"
        body = resp.json()
        assert body["customers"] == 3
        assert body["orders"] == 2
        assert float(body["revenue"]) == 61.0


# ---------------------------------------------------------------- B7
def test_b7_every_placed_order_is_audited(server):
    order_ids = []
    for _ in range(5):
        resp = server.post(
            "/orders", json={"customer_id": 2, "items": [{"product_id": 6, "quantity": 1}]}
        )
        assert resp.status_code == 201, f"checkout failed with {resp.status_code}"
        order_ids.append(resp.json()["id"])

    time.sleep(1.5)
    audited = db_val(
        "SELECT count(*) FROM audit_log WHERE action = 'order.placed' "
        "AND entity_id = ANY($1::int[])",
        order_ids,
    )
    assert audited == 5, f"only {audited} of 5 placed orders were audited"


# ---------------------------------------------------------------- B8
def test_b8_search_does_not_hold_a_transaction_open(server):
    assert server.get("/products/search", params={"q": "tee"}).status_code == 200
    time.sleep(1.0)

    idle = db_val(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND state = 'idle in transaction'"
    )
    assert idle == 0, f"{idle} connection(s) left idle in transaction after the request"

    async def migrate():
        conn = await asyncpg.connect(PG_DSN)
        try:
            await conn.execute("SET lock_timeout = '2s'")
            await conn.execute("ALTER TABLE products ADD COLUMN note text")
        finally:
            await conn.close()

    try:
        asyncio.run(migrate())
    except asyncpg.exceptions.LockNotAvailableError:
        pytest.fail("a schema migration on products is blocked by the search endpoint")


# ---------------------------------------------------------------- decoys
def test_d1_daily_report_background_job(server):
    today = datetime.now(timezone.utc).date().isoformat()
    resp = server.post("/admin/reports/daily", json={"day": today})
    assert resp.status_code == 202

    deadline = time.time() + 5
    count = None
    while time.time() < deadline:
        count = db_val("SELECT order_count FROM daily_reports WHERE day = $1::date", datetime.fromisoformat(today).date())
        if count is not None:
            break
        time.sleep(0.2)
    assert count == 2


def test_d2_newsletter_subscribe_is_idempotent(server):
    for _ in range(2):
        resp = server.post("/customers/2/newsletter")
        assert resp.status_code == 200, f"newsletter opt-in failed with {resp.status_code}"
        assert resp.json() == {"customer_id": 2, "newsletter_opt_in": True}

    assert db_val("SELECT count(*) FROM newsletter_syncs WHERE customer_id = 2") == 1
    assert db_val("SELECT newsletter_opt_in FROM customers WHERE id = 2") is True
