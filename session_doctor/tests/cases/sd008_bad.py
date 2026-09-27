# SD008 BAD – session factory called at module level
from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker()  # SD008: module-level factory instantiation (factory registered)

# Also: session created and never closed
db = SessionLocal()  # SD008: local variable but this is module-level
