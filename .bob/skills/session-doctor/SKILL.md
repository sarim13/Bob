---
name: session-doctor
description: Scan → prove → fix → verify playbook for async SQLAlchemy session-ownership bugs in a FastAPI app. Use when fixing or reviewing database session handling.
---

# Session Doctor playbook

The convention being enforced: **one session per request, one owner, one commit, before the response is returned.** Helpers `flush()`, never `commit()`. Concurrent tasks get their own sessions. `expire_on_commit=False`. Relationships read in async code are eager-loaded.

## 1. Scan (deterministic, no guessing)

```
python -m session_doctor scan <app_dir> --format json --out sd_report.json --fail-on never
```

Every `high` finding is a confirmed bug and goes on the work list. `needs_review` findings: read the code and decide; do not change them unless you can show a failure.

## 2. Prove

For each high finding, write or describe a reproduction of its symptom before fixing:

| Rule | Symptom to reproduce |
|---|---|
| SD001 commit-after-yield | Constraint violation still returns 2xx; row not saved |
| SD002 helper-commits | Later validation fails but earlier writes persisted |
| SD004 lazy-relationship | `MissingGreenlet` 500 on attribute access |
| SD005 begin-after-autobegin | "A transaction is already begun" 500 |
| SD006 shared-session-concurrency | 500 from `asyncio.gather` on one session; leaked connection |
| SD007 unsafe-background-work | Background task writes are lost / session closed errors |
| SD008 session-outlives-request | Connection stays "idle in transaction"; blocks `ALTER TABLE` |

## 3. Fix (one-owner pattern)

- **SD001:** do NOT wrap `yield` in `async with db.begin()` (still commits after the response on FastAPI ≥ 0.118). Commit explicitly in the route before returning and map `IntegrityError` to 409, or use `Depends(get_db, scope="function")`.
- **SD002:** helpers call `flush()`; the route commits once at the end. Set `expire_on_commit=False` on the sessionmaker.
- **SD004:** add `selectinload(Model.rel)` for every relationship that is read.
- **SD005:** remove the explicit `begin()`; mutate, `flush()`, let the owner commit. `begin_nested()` savepoints are fine.
- **SD006:** await queries sequentially, or give each concurrent task its own session.
- **SD007:** await the work inside the request transaction before commit, or open a new session inside the task.
- **SD008:** build the object per request from the request session; no module-level sessions.

Leave code the scanner does not flag alone (e.g. a `BackgroundTasks` job that opens its own session, or a `begin_nested()` savepoint followed by an explicit commit).

## 4. Verify — you are only done when both are true

```
python -m session_doctor scan <app_dir>        # must exit 0 (no high findings)
<project test command>                          # must pass
```

Finish with the before/after scanner summary lines and the list of findings fixed.
