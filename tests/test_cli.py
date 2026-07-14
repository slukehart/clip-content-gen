"""CLI dispatch tests: each subcommand routes to the right handler with the right
args. All side-effecting leaves (engine, session, network, Discord) are mocked."""
import pytest
from unittest.mock import patch, MagicMock
from clipscore.cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])


def test_poll_routes_to_run_once():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.run_once", return_value={"status": "ok"}) as m:
        main(["poll"])
    m.assert_called_once()


def test_rank_passes_top_and_niche():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.format_table", return_value="board"), \
         patch("clipscore.cli.ranked_rows", return_value=[]) as m:
        main(["rank", "--top", "3", "--niche", "gaming"])
    _, kwargs = m.call_args
    assert kwargs["top"] == 3 and kwargs["niche"] == "gaming"


def test_rank_defaults():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.format_table", return_value="board"), \
         patch("clipscore.cli.ranked_rows", return_value=[]) as m:
        main(["rank"])
    _, kwargs = m.call_args
    assert kwargs["top"] == 10 and kwargs["niche"] is None


def test_smoke_passes_db_path():
    with patch("clipscore.cli.run_smoke") as m:
        main(["smoke", "tmp.db"])
    m.assert_called_once_with("tmp.db")


def test_smoke_default_db():
    with patch("clipscore.cli.run_smoke") as m:
        main(["smoke"])
    m.assert_called_once_with("smoke_clipscore.db")


def test_setup_creates_and_seeds():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.Base") as base, \
         patch("clipscore.cli.seed_all") as seed:
        main(["setup"])
    base.metadata.create_all.assert_called_once()
    seed.assert_called_once()


def test_bot_routes_to_run_bot_with_session_factory():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.run_bot") as m:
        main(["bot"])
    from clipscore.cli import SessionLocal
    m.assert_called_once_with(SessionLocal)


def test_extract_routes_to_enrich_batch():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.enrich_batch", return_value={"processed": 3}) as m, \
         patch("clipscore.cli.generate_coverage_spike_report") as report_m:
        main(["extract"])
    m.assert_called_once()
    _, kwargs = m.call_args
    assert kwargs["only_stale"] is True
    report_m.assert_not_called()


def test_extract_report_routes_to_report_driver():
    with patch("clipscore.cli.get_engine"), \
         patch("clipscore.cli.SessionLocal", MagicMock()), \
         patch("clipscore.cli.enrich_batch") as enrich_m, \
         patch("clipscore.cli.generate_coverage_spike_report", return_value="content") as m:
        main(["extract", "--report"])
    m.assert_called_once()
    enrich_m.assert_not_called()
