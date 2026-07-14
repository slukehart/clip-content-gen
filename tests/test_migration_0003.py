import subprocess, sqlite3, os, sys

def test_migration_adds_alerts_table(tmp_path):
    # Mirrors tests/test_migration_0002.py: drive alembic in a subprocess with
    # CLIPSCORE_DB_URL set (env.py reads settings, ignoring set_main_option).
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {row[1] for row in con.execute("PRAGMA table_info(alerts)")}
    con.close()
    assert "alerts" in tables
    assert {"id", "campaign_id", "epoch", "niche", "cvs_niche_percentile", "alerted_at"} <= cols
