import subprocess, sqlite3, os

def test_upgrade_creates_tables(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run(["alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"campaigns", "campaign_snapshots", "fetch_events",
            "platform_trust", "niche_baselines", "campaign_scores", "outcomes"} <= names
