# Database session rules (enforced in CI by session_doctor)

When writing or editing FastAPI + SQLAlchemy code in this workspace:

1. One `AsyncSession` per request, obtained from a dependency. Never create sessions at module level or store them on long-lived objects.
2. Only the route (the owner) commits, and it commits **before returning**. Never commit after `yield` in a dependency.
3. Service/helper functions that receive a session call `flush()`, never `commit()` or `begin()`.
4. Never share one session across `asyncio.gather`, `create_task` or background tasks. A background task opens its own session.
5. Use `expire_on_commit=False` and eager-load (`selectinload`/`joinedload`) every relationship read in async code.
6. Before finishing, run `python -m session_doctor scan <app_dir>` and make sure it reports 0 high findings.
