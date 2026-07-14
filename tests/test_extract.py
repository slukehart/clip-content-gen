from clipscore.ingest.extract import extract_requirements

def test_cap_observed():
    r = extract_requirements("Great campaign. Max $500 per video. Post daily.")
    assert r["cap_per_post_usd"] == 500.0
    assert r["cap_provenance"] == "observed"

def test_min_views():
    r = extract_requirements("Minimum Floor: 5,000 views required to earn.")
    assert r["min_views_threshold"] == 5000

def test_min_payout():
    r = extract_requirements("Minimum payout $50 before withdrawal.")
    assert r["min_payout_threshold_usd"] == 50.0

def test_absent_when_none_or_no_match():
    for d in (None, "", "Just vibes, clip our streams."):
        r = extract_requirements(d)
        assert r["cap_per_post_usd"] is None
        assert r["cap_provenance"] == "absent"
        assert r["min_views_threshold"] is None
        assert r["min_payout_threshold_usd"] is None
