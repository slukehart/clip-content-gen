import re
from clipscore.time import utcnow_iso

def test_utcnow_iso_format():
    value = utcnow_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
