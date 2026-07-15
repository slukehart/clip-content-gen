from clipscore.factory.extract import (
    RegexExtractor, merge_extractions, ExtractedTargets, apply_to_campaign, compute_input_hash,
)
from clipscore.db.models import Campaign


def test_regex_pulls_drive_bank_and_handle():
    d = "Clip @diego content. Footage: https://drive.google.com/drive/folders/AbC"
    e = RegexExtractor().extract(d, None, ["tiktok"])
    assert e.content_bank_url == "https://drive.google.com/drive/folders/AbC"
    assert "@diego" in e.target_creator
    assert e.provenance["content_bank_url"] == "description"
    assert e.provenance["target_creator"] == "description"


def test_platforms_default_to_base_when_silent():
    e = RegexExtractor().extract("Clip our stuff.", None, ["tiktok", "instagram"])
    assert e.target_platforms == ["tiktok", "instagram"]
    assert e.provenance["target_platforms"] == "allowed_socials"  # defaulted, not read from text


def test_no_match_leaves_fields_absent():
    e = RegexExtractor().extract("Clip our stuff, nothing special here.", None, ["tiktok"])
    assert e.content_bank_url is None
    assert e.provenance["content_bank_url"] == "absent"
    assert e.target_creator == []
    assert e.provenance["target_creator"] == "absent"
    assert e.clip_min_len_s is None
    assert e.provenance["clip_min_len_s"] == "absent"
    assert e.clip_max_len_s is None
    assert e.provenance["clip_max_len_s"] == "absent"
    assert e.caption_rules is None
    assert e.provenance["caption_rules"] == "absent"
    assert e.banned_content is None
    assert e.provenance["banned_content"] == "absent"


def test_no_description_or_page_text_absent_and_platforms_default():
    e = RegexExtractor().extract(None, None, ["tiktok"])
    assert e.content_bank_url is None
    assert e.provenance["content_bank_url"] == "absent"
    assert e.target_platforms == ["tiktok"]
    assert e.provenance["target_platforms"] == "allowed_socials"


def test_handle_regex_ignores_email_local_part():
    e = RegexExtractor().extract("Email us at foo@bar.com for details.", None, ["tiktok"])
    assert e.target_creator == []
    assert e.provenance["target_creator"] == "absent"


def test_merge_prefers_llm_and_tags_whop_page():
    regex = ExtractedTargets(target_platforms=["tiktok"], provenance={})
    llm = ExtractedTargets(clip_min_len_s=15, clip_max_len_s=60,
                           provenance={"clip_min_len_s": "whop_page", "clip_max_len_s": "whop_page"})
    m = merge_extractions(regex, llm, ["tiktok"])
    assert m.clip_min_len_s == 15 and m.provenance["clip_min_len_s"] == "whop_page"
    assert m.clip_max_len_s == 60 and m.provenance["clip_max_len_s"] == "whop_page"


def test_merge_falls_back_to_regex_when_llm_absent():
    regex = ExtractedTargets(
        content_bank_url="https://drive.google.com/x",
        target_creator=["@a"],
        provenance={"content_bank_url": "description", "target_creator": "description"},
    )
    llm = ExtractedTargets(provenance={})
    m = merge_extractions(regex, llm, ["tiktok"])
    assert m.content_bank_url == "https://drive.google.com/x"
    assert m.provenance["content_bank_url"] == "description"
    assert m.target_creator == ["@a"]
    assert m.provenance["target_creator"] == "description"


def test_merge_absent_when_neither_source_has_value():
    regex = ExtractedTargets(provenance={})
    llm = ExtractedTargets(provenance={})
    m = merge_extractions(regex, llm, ["tiktok"])
    assert m.caption_rules is None
    assert m.provenance["caption_rules"] == "absent"


def test_apply_writes_json_and_provenance(session):
    c = Campaign(source="cr", external_id="x", url="u", status="active")
    apply_to_campaign(c, ExtractedTargets(target_creator=["@a"], target_platforms=["tiktok"],
                                          provenance={"target_creator": "description"}))
    assert c.target_creator == '["@a"]'
    assert '"target_creator": "description"' in c.extract_provenance


def test_apply_covers_all_seven_fields(session):
    c = Campaign(source="cr", external_id="y", url="u", status="active")
    extracted = ExtractedTargets(
        content_bank_url="https://drive.google.com/x",
        target_creator=["@a", "@b"],
        target_platforms=["tiktok", "instagram"],
        clip_min_len_s=15,
        clip_max_len_s=60,
        caption_rules="no profanity",
        banned_content="politics",
        provenance={
            "content_bank_url": "description",
            "target_creator": "description",
            "target_platforms": "allowed_socials",
            "clip_min_len_s": "whop_page",
            "clip_max_len_s": "whop_page",
            "caption_rules": "whop_page",
            "banned_content": "whop_page",
        },
    )
    apply_to_campaign(c, extracted)
    assert c.content_bank_url == "https://drive.google.com/x"
    assert c.target_creator == '["@a", "@b"]'
    assert c.target_platforms == '["tiktok", "instagram"]'
    assert c.clip_min_len_s == 15
    assert c.clip_max_len_s == 60
    assert c.caption_rules == "no profanity"
    assert c.banned_content == "politics"

    import json
    prov = json.loads(c.extract_provenance)
    for field in ("content_bank_url", "target_creator", "target_platforms",
                  "clip_min_len_s", "clip_max_len_s", "caption_rules", "banned_content"):
        assert field in prov


def test_apply_stamps_input_hash_of_requirements(session):
    c = Campaign(source="cr", external_id="z", url="u", status="active",
                 requirements_raw="Clip @diego.")
    apply_to_campaign(c, ExtractedTargets())
    assert c.extract_input_hash == compute_input_hash("Clip @diego.")


def test_input_hash_changes_with_requirements_and_is_stable():
    h1 = compute_input_hash("Clip @diego.")
    assert h1 == compute_input_hash("Clip @diego.")   # deterministic
    assert h1 != compute_input_hash("Clip @maria.")   # tracks the input text
    # None and "" hash identically (both empty payload)
    assert compute_input_hash(None) == compute_input_hash("")
