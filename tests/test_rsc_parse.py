from pathlib import Path
from clipscore.ingest.rsc import parse_discover

FIX = Path("tests/fixtures/contentrewards/discover_golden.html")

def test_parses_and_dedups():
    camps = parse_discover(FIX.read_text(encoding="utf-8"))
    ids = [c["id"] for c in camps]
    assert len(camps) == 5                     # 6 raw entries -> 5 after dedup-by-id
    assert len(set(ids)) == 5
    assert "dd9f7918-e51d-4935-9f23-5935c783774a" in ids

def test_money_unescaped_but_string():
    camps = {c["id"]: c for c in parse_discover(FIX.read_text(encoding="utf-8"))}
    c = camps["dd9f7918-e51d-4935-9f23-5935c783774a"]
    assert c["pricePerView"] == "$1.50"        # single $, coercion happens later
    assert c["totalBudget"] == "$250,000"
    assert c["whopExperienceId"].startswith("exp_")

def test_empty_or_garbage_returns_empty():
    assert parse_discover("") == []
    assert parse_discover("<html><body>no payload</body></html>") == []
