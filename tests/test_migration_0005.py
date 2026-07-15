import subprocess, sqlite3, os, sys


def test_migration_adds_extract_input_hash(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    ccols = {row[1] for row in con.execute("PRAGMA table_info(campaigns)")}
    con.close()
    assert "extract_input_hash" in ccols
