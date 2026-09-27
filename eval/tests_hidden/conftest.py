"""Hidden test harness for the shopfront fixture.

Each test gets a freshly seeded database and a freshly started uvicorn
process, so bugs that leak connections or hold transactions open cannot
bleed from one test into the next.

Point SHOPFRONT_DIR at the app folder (the one containing app/ and scripts/).
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import asyncpg
import httpx
import pytest

SHOPFRONT_DIR = Path(os.environ.get("SHOPFRONT_DIR", "../examples/shopfront")).resolve()
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/shopfront"
)
PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
PORT = int(os.environ.get("SHOPFRONT_TEST_PORT", "8765"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def _env():
    env = dict(os.environ)
    env["DATABASE_URL"] = DATABASE_URL
    env["PYTHONPATH"] = str(SHOPFRONT_DIR)
    return env


def db_fetch(sql: str, *args):
    async def run():
        conn = await asyncpg.connect(PG_DSN)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def db_val(sql: str, *args):
    rows = db_fetch(sql, *args)
    return rows[0][0] if rows else None


def db_exec(sql: str, *args):
    async def run():
        conn = await asyncpg.connect(PG_DSN)
        try:
            return await conn.execute(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def _terminate_app_backends():
    db_exec(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid()"
    )


@pytest.fixture()
def server():
    if not (SHOPFRONT_DIR / "app" / "main.py").exists():
        pytest.exit(f"SHOPFRONT_DIR does not look like the app folder: {SHOPFRONT_DIR}")

    _terminate_app_backends()
    subprocess.run(
        [sys.executable, "-m", "scripts.seed", "--reset"],
        cwd=SHOPFRONT_DIR,
        env=_env(),
        check=True,
        capture_output=True,
    )

    log_path = Path(__file__).parent / ".server.log"
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=SHOPFRONT_DIR,
        env=_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError(f"server did not start; see {log_path}")

    client = httpx.Client(base_url=BASE_URL, timeout=10)
    try:
        yield client
    finally:
        client.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()
        _terminate_app_backends()
