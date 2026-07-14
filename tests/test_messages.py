from clipscore.bot.messages import format_alert, format_top, format_summary, CAVEAT, NOT_A_GATE

def _payload():
    return dict(campaign_id="c1", title="Cool Campaign", niche="gaming",
                url="http://x/c1", percentile=0.95, cvs_raw=12.3, epoch=0)

def test_alert_carries_both_literals_and_link():
    out = format_alert(_payload())
    assert CAVEAT in out
    assert NOT_A_GATE in out
    assert "http://x/c1" in out
    assert "gaming" in out and "Cool Campaign" in out
    assert "$/hr" not in out

def test_top_carries_caveat_no_hr():
    rows = [dict(campaign_id="c1", title="T", niche="gaming", cpm_usd=2.0, net_cpm=1.8,
                 budget_health=0.7, sat_factor=0.8, cvs_raw=9.0, cvs_niche_percentile=0.9)]
    out = format_top(rows, "gaming")
    assert CAVEAT in out and "$/hr" not in out
    assert "gaming" in out

def test_top_empty():
    assert "no scored campaigns" in format_top([], None).lower()

def test_summary_movers_labeled_relative_not_improved():
    top = [dict(niche="gaming", title="T", cvs_niche_percentile=0.9)]
    movers = [dict(campaign_id="c1", title="T", niche="gaming", current=0.9, past=0.3, delta=0.6)]
    out = format_summary(top, movers, "2026-07-14T13:00:00Z")
    assert CAVEAT in out
    assert "change in relative niche standing" in out.lower()
    assert "improved" not in out.lower()
    assert "$/hr" not in out

def test_alert_null_title_renders_cleanly():
    # title-less campaign must not render a literal "None" or crash
    p = dict(campaign_id="c1", title=None, niche="gaming", url=None,
             percentile=0.95, cvs_raw=1.0, epoch=0)
    out = format_alert(p)
    assert "**None**" not in out
    assert "(untitled)" in out
    assert CAVEAT in out and NOT_A_GATE in out
