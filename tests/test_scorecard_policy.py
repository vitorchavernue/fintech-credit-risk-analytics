"""Score scale, risk grades and credit policy simulation."""

import math

import numpy as np
import pandas as pd
import pytest

from credit.policy import champion_challenger, cutoff_simulation, fairness_check
from credit.scorecard import assign_grade, probability_to_score, risk_grades


def test_score_scale():
    # Odds 50:1 (probability of default 1/51) -> 600 points; doubling the odds adds 20 points.
    assert probability_to_score(1 / 51) == 600
    assert probability_to_score(1 / 101) == 620
    assert probability_to_score(0.5) < probability_to_score(0.1)  # higher risk, lower score


def test_risk_grades_have_equal_size_on_training_scores():
    scores = np.arange(1000, dtype=float)
    grades = risk_grades(scores)
    assigned = assign_grade(scores, grades)
    counts = pd.Series(assigned).value_counts()
    assert list(grades["risk_grade"]) == ["A", "B", "C", "D", "E"]
    assert counts.min() == counts.max() == 200
    assert assign_grade(np.array([999.0]), grades)[0] == "A"
    assert assign_grade(np.array([0.0]), grades)[0] == "E"


@pytest.fixture
def customers():
    rng = np.random.default_rng(7)
    n = 20_000
    score = rng.normal(600, 40, n)
    probability = 1 / (1 + np.exp((score - 520) / 25))
    return pd.DataFrame(
        {
            "application_id": range(n),
            "defaulted": (rng.random(n) < probability).astype(int),
            "credit_amount": rng.uniform(1e5, 1e6, n),
            "credit_score": score,
            "gender": rng.choice(["F", "M"], n),
            "champion_approves": rng.random(n) < 0.85,  # rules unrelated to risk
        }
    )


def test_cutoff_simulation(customers):
    result = cutoff_simulation(customers)
    assert result["target_approval_rate"].tolist()[0] == 0.5
    assert result["approval_rate"].iloc[-1] == 1.0 and result["defaults_avoided"].iloc[-1] == 0
    # Approving fewer customers always means a lower default rate among those approved.
    assert result["default_rate_approved"].is_monotonic_increasing
    assert result["recommended"].sum() >= 1


def test_challenger_beats_random_rules(customers):
    result = champion_challenger(customers)
    champion, challenger = result.iloc[0], result.iloc[1]
    assert champion["approval_rate"] == pytest.approx(challenger["approval_rate"], abs=0.01)
    assert challenger["default_rate_approved"] < champion["default_rate_approved"]
    assert bool(result["significant"].iloc[0])
    assert result["live_test_applications_per_arm"].iloc[0] > 0


def test_fairness_check(customers):
    result = fairness_check(customers, minimum_score=560)
    assert set(result["gender"]) == {"F", "M"}
    assert result["approval_ratio_vs_highest"].max() == 1.0
    assert not math.isnan(result["approval_ratio_vs_highest"].min())
