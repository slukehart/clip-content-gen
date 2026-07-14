import pytest
from clipscore.scoring import formula as f

def test_net_cpm():
    assert f.net_cpm(2.0, 0.10) == pytest.approx(1.8)

def test_raw_earnings():
    assert f.raw_earnings(1.8, 8000) == pytest.approx(14.4)

def test_capped_earnings_observed():
    assert f.capped_earnings(100.0, 30.0, "observed", 500.0) == 30.0

def test_capped_earnings_observed_below_cap():
    assert f.capped_earnings(20.0, 30.0, "observed", 500.0) == 20.0

def test_capped_earnings_absent_uses_default_cap():
    assert f.capped_earnings(900.0, None, "absent", 500.0) == 500.0

def test_capped_earnings_observed_but_null_cap_falls_back_to_default():
    # provenance says observed but the value is missing -> conservative default
    assert f.capped_earnings(900.0, None, "observed", 500.0) == 500.0

def test_sat_factor_normal():
    assert f.sat_factor(1000.0, 10) == pytest.approx(0.5)   # 100/200

def test_sat_factor_caps_at_one():
    assert f.sat_factor(100000.0, 1) == 1.0

def test_sat_factor_missing_clippers():
    assert f.sat_factor(1000.0, None) == 0.8

def test_sat_factor_missing_remaining():
    assert f.sat_factor(None, 10) == 0.8

def test_sat_factor_zero_clippers_no_div0():
    assert f.sat_factor(200.0, 0) == pytest.approx(1.0)     # max(0,1)=1 -> 200/200

def test_ev_per_clip_product():
    assert f.ev_per_clip(30.0, 0.55, 0.7, 0.8, 1.0, 0.5) == pytest.approx(30*0.55*0.7*0.8*1.0*0.5)

def test_cvs_raw():
    assert f.cvs_raw(9.24, 0.75) == pytest.approx(12.32)
