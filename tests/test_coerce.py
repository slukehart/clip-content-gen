import pytest
from clipscore.ingest.coerce import money_to_float, views_to_int, to_int, to_float

@pytest.mark.parametrize("s,expected", [
    ("$1.50", 1.5), ("$0.15", 0.15), ("$250,000", 250000.0),
    ("$86,690.35", 86690.35), ("0", 0.0), ("", None), (None, None), ("n/a", None),
])
def test_money_to_float(s, expected):
    assert money_to_float(s) == expected

@pytest.mark.parametrize("s,expected", [
    ("51.4M", 51_400_000), ("9.1M", 9_100_000), ("226.2K", 226_200),
    ("811.8K", 811_800), ("2.1B", 2_100_000_000), ("0", 0),
    ("1234", 1234), ("", None), (None, None),
])
def test_views_to_int(s, expected):
    assert views_to_int(s) == expected

def test_to_int_and_float():
    assert to_int(3728) == 3728 and to_int("5") == 5 and to_int(None) is None
    assert to_float("2.0") == 2.0 and to_float(None) is None
