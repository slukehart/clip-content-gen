import pytest
from clipscore.scoring.percentile import empirical_cdf

def test_single_element_is_top():
    assert empirical_cdf(5.0, [5.0]) == 1.0

def test_max_is_one():
    assert empirical_cdf(9.0, [1.0, 5.0, 9.0]) == 1.0

def test_min_is_fraction_not_zero():
    assert empirical_cdf(1.0, [1.0, 5.0, 9.0]) == pytest.approx(1/3)

def test_middle():
    assert empirical_cdf(5.0, [1.0, 5.0, 9.0]) == pytest.approx(2/3)

def test_ties_equal():
    pop = [1.0, 5.0, 5.0, 9.0]
    assert empirical_cdf(5.0, pop) == pytest.approx(3/4)   # both 5.0s get 3/4
