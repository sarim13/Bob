# SD003 GOOD – expire_on_commit=False prevents stale read
from sqlalchemy.orm import sessionmaker, Session

SessionLocal = sessionmaker(expire_on_commit=False)


def update_user(session: Session, user):
    user.name = "new"
    session.commit()
    _ = user.name  # safe: expire_on_commit=False
    return user
