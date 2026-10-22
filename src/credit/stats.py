"""Statistical tools used to decide whether a difference in default rates is real or chance.

Every function works on counts (customers and defaults), so it runs in milliseconds even
for millions of customers: Spark does the counting, these functions do the statistics.

Plain-language glossary used in the reports:
* default rate: share of customers who defaulted;
* confidence interval (95%): range where the true rate is, with 95% confidence;
* p-value: chance of seeing a difference this large if there were no real difference
  (below 5% -> "statistically significant");
* q-value: the p-value corrected because many segments are tested at once
  (Benjamini-Hochberg), which avoids "finding" effects that are just luck;
* relative risk: how many times more likely one group is to default than the other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats as st


def wilson_interval(defaults: int, customers: int, confidence: float = 0.95) -> tuple[float, float]:
    """Confidence interval of a default rate (Wilson method: reliable even for small groups)."""
    if customers == 0:
        return (math.nan, math.nan)
    z = st.norm.ppf(1 - (1 - confidence) / 2)
    rate = defaults / customers
    centre = (rate + z**2 / (2 * customers)) / (1 + z**2 / customers)
    margin = z * math.sqrt(rate * (1 - rate) / customers + z**2 / (4 * customers**2)) / (1 + z**2 / customers)
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True)
class ProportionTest:
    """Result of comparing the default rate of group A with group B."""

    rate_a: float
    rate_b: float
    difference: float  # rate A - rate B, in percentage points / 100
    ci_low: float  # 95% confidence interval of the difference
    ci_high: float
    relative_risk: float  # rate A / rate B
    z: float
    p_value: float


def two_proportion_test(defaults_a: int, customers_a: int, defaults_b: int, customers_b: int) -> ProportionTest:
    """Two-proportion z-test: is the default rate of A different from the rate of B?"""
    p_a, p_b = defaults_a / customers_a, defaults_b / customers_b
    # Test assumes "no difference": both groups share the same rate (pooled rate).
    pooled = (defaults_a + defaults_b) / (customers_a + customers_b)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / customers_a + 1 / customers_b))
    z = (p_a - p_b) / se_pooled if se_pooled > 0 else 0.0
    p_value = 2 * (1 - st.norm.cdf(abs(z)))
    # Confidence interval of the difference uses each group's own rate.
    se_diff = math.sqrt(p_a * (1 - p_a) / customers_a + p_b * (1 - p_b) / customers_b)
    margin = st.norm.ppf(0.975) * se_diff
    diff = p_a - p_b
    return ProportionTest(
        rate_a=p_a,
        rate_b=p_b,
        difference=diff,
        ci_low=diff - margin,
        ci_high=diff + margin,
        relative_risk=p_a / p_b if p_b > 0 else math.inf,
        z=z,
        p_value=float(p_value),
    )


def chi_square_test(defaults: list[int], customers: list[int]) -> tuple[float, float, int, float]:
    """Chi-square test of independence: does the default rate change across the segments
    of one dimension (e.g. education levels)? Returns chi2, p-value, degrees of freedom and
    Cramér's V (strength of the association: 0 = none, 0.1 = small, 0.3 = medium, 0.5 = large).
    """
    table = np.array([[d, n - d] for d, n in zip(defaults, customers, strict=True)], dtype=float)
    table = table[table.sum(axis=1) > 0]
    chi2, p_value, dof, _ = st.chi2_contingency(table, correction=False)
    total = table.sum()
    cramers_v = math.sqrt(chi2 / (total * (min(table.shape) - 1))) if total > 0 else 0.0
    return float(chi2), float(p_value), int(dof), cramers_v


def information_value(defaults: list[int], customers: list[int]) -> float:
    """Information Value (IV): the credit market's standard measure of how well a
    characteristic separates good from bad customers.
    Usual reading: below 0.02 useless, 0.02-0.1 weak, 0.1-0.3 medium, above 0.3 strong.
    """
    bad = np.asarray(defaults, dtype=float)
    good = np.asarray(customers, dtype=float) - bad
    # Half a customer is added to empty cells so a segment with no defaults does not break the formula.
    bad_share = (bad + 0.5) / (bad.sum() + 0.5 * len(bad))
    good_share = (good + 0.5) / (good.sum() + 0.5 * len(good))
    return float(np.sum((good_share - bad_share) * np.log(good_share / bad_share)))


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Adjusts p-values when many tests are run together (false discovery rate control).

    Testing 40 segments at 5% would produce about 2 "significant" results by pure luck;
    the adjusted values (q-values) remove that effect.
    """
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    # Each q-value is the smallest adjusted value from its rank onwards (keeps the order).
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(n)
    q[order] = np.clip(q_sorted, 0, 1)
    return q.tolist()


def sample_size_two_proportions(rate_a: float, rate_b: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Customers needed IN EACH GROUP of an A/B test to detect the change from rate A to rate B.

    ``power`` = chance of detecting the change if it really exists (80% is the market standard).
    """
    if rate_a == rate_b:
        return 0
    z_alpha = st.norm.ppf(1 - alpha / 2)
    z_beta = st.norm.ppf(power)
    pooled = (rate_a + rate_b) / 2
    numerator = (
        z_alpha * math.sqrt(2 * pooled * (1 - pooled))
        + z_beta * math.sqrt(rate_a * (1 - rate_a) + rate_b * (1 - rate_b))
    ) ** 2
    return math.ceil(numerator / (rate_a - rate_b) ** 2)


def roc_auc(scores: np.ndarray, defaulted: np.ndarray) -> float:
    """Probability that a random defaulter gets a higher risk than a random good customer
    (0.5 = no better than a coin, 1.0 = perfect ranking)."""
    scores = np.asarray(scores, dtype=float)
    defaulted = np.asarray(defaulted, dtype=int)
    ranks = st.rankdata(scores)
    n_bad = defaulted.sum()
    n_good = len(defaulted) - n_bad
    return float((ranks[defaulted == 1].sum() - n_bad * (n_bad + 1) / 2) / (n_bad * n_good))


def ks_statistic(scores: np.ndarray, defaulted: np.ndarray) -> float:
    """Kolmogorov-Smirnov: largest gap between how bad and good customers are spread along
    the risk scale. The credit market reads KS above 0.30 as a good separation."""
    scores = np.asarray(scores, dtype=float)
    defaulted = np.asarray(defaulted, dtype=int)
    result = st.ks_2samp(scores[defaulted == 1], scores[defaulted == 0])
    return float(result.statistic)
