from clipscore.config import Settings

def test_alert_config_defaults():
    # _env_file=None keeps this hermetic: assert code defaults without reading a
    # developer's local .env (which may set e.g. CLIPSCORE_DISCORD_ALERT_CHANNEL_ID).
    s = Settings(_env_file=None)
    assert s.alert_percentile == 0.90
    assert s.min_niche_sample == 5
    assert s.discord_alert_channel_id is None
    assert s.summary_hour_et == 9
