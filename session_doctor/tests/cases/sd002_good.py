# SD002 GOOD – helper only flushes; route commits
from sqlalchemy.orm import Session


def save_item(session: Session, item):
    session.add(item)
    session.flush()  # only flush in helper


def route_handler(session: Session):
    save_item(session, object())
    session.commit()  # owner commits
    return {"ok": True}
