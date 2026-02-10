from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import config


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_status() -> bool:
    """Simple health check for the primary database connection."""

    try:
        with engine.connect() as conn:  # type: ignore[call-arg]
            conn.execute("SELECT 1")  # type: ignore[arg-type]
        return True
    except Exception:
        return False
