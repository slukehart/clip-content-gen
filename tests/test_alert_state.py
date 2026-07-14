from clipscore.bot.state import already_alerted, record_alert


def test_not_alerted_initially(session):
    assert already_alerted(session, "c1", 0) is False


def test_record_then_alerted(session):
    record_alert(session, "c1", 0, "gaming", 0.95, "2026-07-14T00:00:00Z")
    assert already_alerted(session, "c1", 0) is True


def test_dedup_is_per_epoch(session):
    record_alert(session, "c1", 0, "gaming", 0.95, "t")
    assert already_alerted(session, "c1", 1) is False   # new epoch: not yet alerted
    record_alert(session, "c1", 1, "gaming", 0.96, "t2")
    assert already_alerted(session, "c1", 1) is True
