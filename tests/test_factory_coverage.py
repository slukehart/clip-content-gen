"""Pure counting tests for factory/coverage.py -- synthetic rows only, no
network/LLM. `coverage_report` takes an iterable of dict-shaped rows with the
extraction fields + `extract_provenance` (a dict of field -> source) + the
raw footage-source inputs (`content_bank_url`, `target_creator`)."""
from clipscore.factory.coverage import coverage_report


def _row(**kw):
    defaults = dict(
        content_bank_url=None,
        target_creator=[],
        target_platforms=[],
        clip_min_len_s=None,
        clip_max_len_s=None,
        caption_rules=None,
        banned_content=None,
        extract_provenance={
            "content_bank_url": "absent",
            "target_creator": "absent",
            "target_platforms": "absent",
            "clip_min_len_s": "absent",
            "clip_max_len_s": "absent",
            "caption_rules": "absent",
            "banned_content": "absent",
        },
    )
    defaults.update(kw)
    return defaults


def test_per_field_coverage_percentages():
    rows = [
        _row(content_bank_url="https://drive.google.com/f/1",
             extract_provenance={"content_bank_url": "description", "target_creator": "absent",
                                  "target_platforms": "absent", "clip_min_len_s": "absent",
                                  "clip_max_len_s": "absent", "caption_rules": "absent",
                                  "banned_content": "absent"}),
        _row(),  # all absent
    ]
    report = coverage_report(rows)
    assert report["total"] == 2
    assert report["field_coverage_pct"]["content_bank_url"] == 50.0
    assert report["field_coverage_pct"]["target_creator"] == 0.0


def test_provenance_breakdown_counts():
    rows = [
        _row(content_bank_url="url1",
             extract_provenance={"content_bank_url": "description", "target_creator": "absent",
                                  "target_platforms": "absent", "clip_min_len_s": "absent",
                                  "clip_max_len_s": "absent", "caption_rules": "absent",
                                  "banned_content": "absent"}),
        _row(content_bank_url="url2",
             extract_provenance={"content_bank_url": "whop_page", "target_creator": "absent",
                                  "target_platforms": "allowed_socials", "clip_min_len_s": "absent",
                                  "clip_max_len_s": "absent", "caption_rules": "absent",
                                  "banned_content": "absent"}),
        _row(),
    ]
    report = coverage_report(rows)
    prov = report["provenance_breakdown"]["content_bank_url"]
    assert prov["description"] == 1
    assert prov["whop_page"] == 1
    assert prov["absent"] == 1
    assert report["provenance_breakdown"]["target_platforms"]["allowed_socials"] == 1
    assert report["provenance_breakdown"]["target_platforms"]["absent"] == 2


def test_footage_source_distribution():
    rows = [
        _row(content_bank_url="https://drive.google.com/f/1"),  # campaign_provided
        _row(target_creator=["@diego"]),                         # named_creator
        _row(),                                                  # none
        _row(content_bank_url="https://drive.google.com/f/2", target_creator=["@x"]),  # bank wins
    ]
    report = coverage_report(rows)
    dist = report["footage_source_distribution"]
    assert dist["campaign_provided"] == 2
    assert dist["named_creator"] == 1
    assert dist["none"] == 1


def test_empty_rows_returns_zeroed_report():
    report = coverage_report([])
    assert report["total"] == 0
    assert report["field_coverage_pct"]["content_bank_url"] == 0.0
    assert report["footage_source_distribution"] == {"campaign_provided": 0, "named_creator": 0, "none": 0}
