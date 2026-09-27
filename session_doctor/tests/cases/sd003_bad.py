# SD003 BAD – read attribute after commit with default expire_on_commit=True
from sqlalchemy.orm import sessionmaker, Session

SessionLocal = sessionmaker()  # expire_on_commit=True by default


def update_user(session: Session, user):
    user.name = "new"
    session.commit()
    _ = user.name  # SD003: expired attribute access after commit
    return user
