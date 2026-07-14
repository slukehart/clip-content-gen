from sqlalchemy import text
from clipscore.db.session import make_engine

def test_wal_enabled_for_file_db(tmp_path):
    db = tmp_path / "t.db"
    engine = make_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
