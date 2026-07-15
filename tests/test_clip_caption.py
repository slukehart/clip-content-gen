from clipscore.db.models import Campaign, Clip
from clipscore.factory.clip.caption import caption_floor, suggest_caption
from clipscore.factory.llm import FakeLLMClient
from clipscore.config import Settings


def _camp(**kw):
    return Campaign(source="cr", external_id="x", status="active", **kw)


def _clip():
    return Clip(source_asset_id=1, platform_variant="tiktok", transcript="great moment",
                engine="fake", status="produced", created_at="2026-07-15T00:00:00Z")


def test_floor_injects_ad_when_rules_silent():
    assert caption_floor(_camp(caption_rules=None)) == "#ad"


def test_floor_preserves_rules_and_ensures_ad():
    out = caption_floor(_camp(caption_rules="Tag @brand"))
    assert "Tag @brand" in out and "#ad" in out


def test_floor_does_not_double_ad():
    out = caption_floor(_camp(caption_rules="cool #ad"))
    assert out.lower().count("#ad") == 1


def test_llm_enrichment_still_forces_ad():
    # LLM returns a caption WITHOUT #ad -> final must still contain it
    s = Settings(_env_file=None, llm_api_key="KEY")
    out = suggest_caption(_camp(caption_rules="Tag @brand"), _clip(), s,
                          llm=FakeLLMClient(text_result="An epic clip you have to see"))
    assert "#ad" in out and "epic clip" in out


def test_no_key_uses_floor():
    out = suggest_caption(_camp(caption_rules="Tag @brand"), _clip(), Settings(_env_file=None))
    assert out.strip().startswith("Tag @brand") and "#ad" in out
