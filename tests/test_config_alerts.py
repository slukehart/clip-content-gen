from clipscore.config import Settings

def test_alert_config_defaults():
    s = Settings()
    assert s.alert_percentile == 0.90
    assert s.min_niche_sample == 5
    assert s.discord_alert_channel_id is None
    assert s.summary_hour_et == 9
