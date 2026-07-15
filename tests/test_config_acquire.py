from clipscore.config import Settings


def test_acquire_config_defaults():
    s = Settings(_env_file=None)  # hermetic — ignore the developer's .env
    assert s.media_dir == "media/"
    assert s.max_media_gb == 50.0
    assert s.raw_retention_days == 14  # already present, used by retention sweep
