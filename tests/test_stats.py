"""Statistical functions checked against known results and reference implementations."""

import math

import numpy as np
import pytest
from scipy import stats as st

from credit import stats


def test_wilson_interval_known_value():
    # 8 defaults in 100 customers -> reference interval 4.1% to 15.0%
    low, high = stats.wilson_interval(8, 100)
    assert low == pytest.approx(0.0411, abs=1e-4)
    assert high == pytest.approx(0.1500, abs=1e-4)


def test_wilson_interval_never_outside_0_1():
    assert stats.wilson_interval(0, 10)[0] == 0.0
    assert stats.wilson_interval(10, 10)[1] == pytest.approx(1.0)


def test_two_proportion_test_matches_chi_square():
    # For a 2x2 table, z squared equals the chi-square statistic (without continuity correction).
    test = stats.two_proportion_test(120, 1000, 80, 1000)
    chi2, p_value, _, _ = st.chi2_contingency([[120, 880], [80, 920]], correction=False)
    assert test.z**2 == pytest.approx(chi2)
    assert test.p_value == pytest.approx(p_value)
    assert test.relative_risk == pytest.approx(1.5)
    assert test.ci_low < test.difference < test.ci_high


def test_chi_square_and_cramers_v():
    chi2, p_value, dof, v = stats.chi_square_test([10, 50, 90], [1000, 1000, 1000])
    assert dof == 2
    assert p_value < 1e-10
    assert 0.1 < v < 0.3  # small association


def test_benjamini_hochberg_reference_example():
    p = [0.01, 0.04, 0.03, 0.005]
    q = stats.benjamini_hochberg(p)
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_sample_size_two_proportions_reference():
    # Classic example: 10% vs 8% at 5% significance and 80% power -> about 3,213 per group
    assert stats.sample_size_two_proportions(0.10, 0.08) == pytest.approx(3213, abs=5)


def test_auc_matches_pairwise_definition():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 300)
    score = y + rng.normal(0, 1, 300)
    pairs = [(a > b) + 0.5 * (a == b) for a in score[y == 1] for b in score[y == 0]]
    assert stats.roc_auc(score, y) == pytest.approx(np.mean(pairs))


def test_ks_perfect_and_random():
    y = np.array([0] * 50 + [1] * 50)
    assert stats.ks_statistic(np.arange(100), y) == pytest.approx(1.0)
    assert stats.ks_statistic(np.ones(100), y) == pytest.approx(0.0)
    assert not math.isnan(stats.ks_statistic(np.random.default_rng(1).random(100), y))


def test_information_value():
    # Identical default rates in every segment -> the characteristic is useless (IV close to 0)
    assert stats.information_value([10, 20], [100, 200]) == pytest.approx(0, abs=1e-3)
    # Very different rates -> strong predictor
    assert stats.information_value([90, 10], [200, 1000]) > 0.3
