from unittest.mock import patch
from clipscore.jobs.poll import run_once


def test_scoring_runs_on_ok(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "ok", "count": 500}), \
         patch("clipscore.jobs.poll.score_all", return_value={"scored": 42}) as m:
        res = run_once(session)
    m.assert_called_once()
    assert res["scored"] == 42


def test_scoring_skipped_on_halted(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "halted"}), \
         patch("clipscore.jobs.poll.score_all") as m:
        res = run_once(session)
    m.assert_not_called()
    assert res["status"] == "halted" and "scored" not in res


def test_scoring_skipped_on_harvest_too_small(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "harvest_too_small", "count": 3}), \
         patch("clipscore.jobs.poll.score_all") as m:
        run_once(session)
    m.assert_not_called()


def test_extraction_failure_never_breaks_poll_result(session):
    """Carried finding: enrich_batch's own query/iteration is not internally
    guarded, so the guard must wrap the entire call at the poll layer -- a
    raised exception there must still leave run_once's ingest/score result
    intact."""
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "ok", "count": 500}), \
         patch("clipscore.jobs.poll.score_all", return_value={"scored": 42}), \
         patch("clipscore.jobs.poll.enrich_batch", side_effect=RuntimeError("boom")) as m:
        res = run_once(session)
    m.assert_called_once()
    assert res["status"] == "ok"
    assert res["scored"] == 42
