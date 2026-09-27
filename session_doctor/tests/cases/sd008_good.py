# SD008 GOOD – factory defined at module level (fine), session only in dependencies
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends

# Factory definition at module level is fine
SessionLocal = sessionmaker(expire_on_commit=False)


def get_db():
    """Proper per-request session via context manager."""
    with SessionLocal() as session:
        yield session  # session is properly managed
