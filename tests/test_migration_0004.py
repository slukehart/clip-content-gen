import subprocess, sqlite3, os, sys

def test_migration_adds_pipeline_b_schema(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ccols = {row[1] for row in con.execute("PRAGMA table_info(campaigns)")}
    con.close()
    assert {"clip_jobs", "source_assets", "clips", "clip_matches"} <= tables
    assert {"content_bank_url", "target_creator", "target_platforms", "clip_min_len_s",
            "clip_max_len_s", "caption_rules", "banned_content", "extract_provenance"} <= ccols
