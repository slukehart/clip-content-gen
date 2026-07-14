from clipscore.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.db_url == "sqlite:///clipscore.db"
    assert s.poll_interval_minutes == 45
    assert s.unseen_polls_to_end == 3
    assert s.harvest_min_campaigns == 50
    assert s.default_p_approval == 0.7
    assert s.default_assumed_cap_usd == 500.0
    assert s.hours_per_clip == 0.75
    assert s.enable_playwright is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("CLIPSCORE_POLL_INTERVAL_MINUTES", "10")
    s = Settings(_env_file=None)
    assert s.poll_interval_minutes == 10
