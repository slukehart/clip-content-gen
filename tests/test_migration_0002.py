import subprocess, sqlite3, os, sys


def test_migration_adds_campaign_type(tmp_path):
    # NOTE: deviates from the task brief's literal test body. alembic/env.py
    # (line 9) unconditionally overwrites sqlalchemy.url from
    # get_settings().db_url, so Config.set_main_option("sqlalchemy.url", ...)
    # is a no-op in this repo — the brief's Config/command.upgrade approach
    # would silently run against the real project db instead of tmp_path.
    # Mirrors the existing tests/test_migration.py pattern: drive alembic in
    # a fresh subprocess with CLIPSCORE_DB_URL set, which is what env.py
    # actually reads.
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    cols = {row[1]: row for row in con.execute("PRAGMA table_info(campaigns)")}
    con.close()
    assert "campaign_type" in cols
    assert cols["campaign_type"][3] == 0  # notnull flag == 0 -> nullable
