from clipscore.config import Settings

def test_source_fetch_settings_defaults():
    s = Settings(_env_file=None)
    assert s.source_base_url == "https://contentrewards.com"
    assert s.discover_path == "/discover"
    assert s.http_timeout_s == 60
    assert "clipscore" in s.user_agent.lower()
