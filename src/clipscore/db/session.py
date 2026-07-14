from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from clipscore.config import get_settings


def _set_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(url: str) -> Engine:
    # in-memory DBs cannot use WAL; only wire pragmas for file-backed sqlite
    is_file_sqlite = url.startswith("sqlite:///") and ":memory:" not in url
    engine = create_engine(url, future=True)
    if is_file_sqlite:
        event.listen(engine, "connect", _set_sqlite_pragmas)
        # trigger one connection so WAL is set immediately
        with engine.connect():
            pass
    return engine


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().db_url)
        SessionLocal.configure(bind=_engine)
    return _engine
