# SD008 BAD – factory call nested inside another call at module level
from sqlalchemy.orm import sessionmaker


class Catalog:
    def __init__(self, session):
        self.session = session


SessionLocal = sessionmaker()

# SD008: SessionLocal() is called inside Catalog() at module level
catalog = Catalog(SessionLocal())
