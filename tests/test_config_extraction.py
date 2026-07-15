from clipscore.config import Settings

def test_extraction_config_defaults():
    s = Settings(_env_file=None)  # hermetic — don't read the developer's .env
    assert s.llm_api_key is None
    assert s.llm_model == "moonshotai/kimi-k2"
    assert s.extract_from_whop_page is True
    assert s.extract_enabled is True
