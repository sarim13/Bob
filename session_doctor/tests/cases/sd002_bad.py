# SD002 BAD – helper commits the session it received
from sqlalchemy.orm import Session


def save_item(session: Session, item):
    session.add(item)
    session.commit()  # SD002: helper should not commit


def route_handler(session: Session):
    save_item(session, object())
    return {"ok": True}
