from clipscore.factory.extract_llm import LLMExtractor
from clipscore.factory.llm import FakeLLMClient
from clipscore.config import Settings


def test_llm_extractor_parses_json_client_result():
    fake = FakeLLMClient(json_result={
        "content_bank_url": "https://drive.google.com/x",
        "target_creator": ["@diego"], "target_platforms": ["tiktok"],
        "clip_min_len_s": 15, "clip_max_len_s": 60,
        "caption_rules": "use #ad", "banned_content": None,
        "provenance": {"content_bank_url": "whop_page", "target_creator": "description",
                       "target_platforms": "description", "clip_min_len_s": "whop_page",
                       "clip_max_len_s": "whop_page", "caption_rules": "whop_page",
                       "banned_content": "absent"},
    })
    e = LLMExtractor(Settings(_env_file=None, llm_api_key="KEY"), client=fake)
    r = e.extract("Clip @diego", "page", ["tiktok"])
    assert r.content_bank_url == "https://drive.google.com/x"
    assert r.target_creator == ["@diego"]
    assert r.clip_min_len_s == 15
    assert r.provenance["content_bank_url"] == "whop_page"


def test_llm_extractor_no_key_raises():
    import pytest
    with pytest.raises(RuntimeError):
        LLMExtractor(Settings(_env_file=None)).extract("d", None, ["tiktok"])


def test_no_anthropic_import_anywhere():
    import pathlib
    src = pathlib.Path("src/clipscore/factory/extract_llm.py").read_text()
    assert "anthropic" not in src
