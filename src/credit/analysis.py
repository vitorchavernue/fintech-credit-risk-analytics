"""Default rate by customer segment, with statistical tests.

Answers questions such as "do customers who paid late before default more?" with
numbers that can be trusted: every rate has a confidence interval, every comparison a
p-value, and the p-values are corrected for the number of comparisons made.

Outputs (gold layer):
* ``agg_default_by_segment``  - default rate of every segment of every dimension
* ``stats_dimension_tests``   - how well each characteristic separates good and bad customers
                                (Information Value, chi-square test, Cramér's V)
* ``stats_hypothesis_tests``  - the business questions, answered one by one
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from credit import stats
from credit.config import ALPHA, LOSS_GIVEN_DEFAULT, Storage
from credit.spark import from_pandas, read_table, write_table

# Dimension tables of the star schema and their key in the fact table.
DIMENSIONS = {
    "payment_behavior": "payment_behavior_key",
    "bureau_status": "bureau_status_key",
    "previous_refusals": "previous_refusals_key",
    "payment_burden": "payment_burden_key",
    "age_band": "age_band_key",
    "income_band": "income_band_key",
    "education_level": "education_key",
}
# Descriptive columns analysed as they are. Gender is analysed only to monitor fairness.
ATTRIBUTES = ["income_type", "contract_type", "region_rating", "housing_type", "gender"]


@dataclass(frozen=True)
class Hypothesis:
    """A business question written as "group A defaults more/less than group B"."""

    question: str
    group_a: str  # SQL condition on the fact table
    group_b: str


HYPOTHESES = [
    Hypothesis(
        "Customers who paid earlier installments late default more than those who always paid on time",
        "payment_behavior_key IN (2, 3)",
        "payment_behavior_key = 1",
    ),
    Hypothesis(
        "Customers with loans overdue now at other institutions default more than those with a clean record",
        "bureau_status_key = 2",
        "bureau_status_key = 1",
    ),
    Hypothesis(
        "Customers already refused by Home Credit default more than those never refused",
        "previous_refusals_key IN (2, 3)",
        "previous_refusals_key = 1",
    ),
    Hypothesis(
        "Customers committing 30% or more of their income to the loan default more",
        "payment_burden_key = 4",
        "payment_burden_key IN (1, 2, 3)",
    ),
    Hypothesis(
        "Customers in the worst-rated regions default more than those in the best-rated regions",
        "region_rating = 3",
        "region_rating = 1",
    ),
    Hypothesis(
        "Customers with higher education default less than those without it",
        "education_key >= 4",
        "education_key BETWEEN 1 AND 3",
    ),
    Hypothesis(
        "Customers without a reported job (mostly pensioners) default less than employed customers",
        "employment_not_reported",
        "NOT employment_not_reported",
    ),
]


def fact_with_labels(spark: SparkSession, storage: Storage) -> DataFrame:
    """Fact table with the label and display order of every dimension."""
    fact = read_table(spark, storage, "gold", "fact_application")
    for name, key in DIMENSIONS.items():
        dim = read_table(spark, storage, "gold", f"dim_{name}").withColumnRenamed("sort_order", f"{name}_order")
        fact = fact.join(F.broadcast(dim), on=key, how="left")
    return fact


def segment_counts(fact: DataFrame) -> pd.DataFrame:
    """Customers, defaults and amounts per segment (counting is done by Spark)."""
    parts = []
    specs = [(name, F.col(name), F.col(f"{name}_order")) for name in DIMENSIONS]
    specs += [(name, F.coalesce(F.col(name).cast("string"), F.lit("Not informed")), F.lit(0)) for name in ATTRIBUTES]
    for dimension, label, order in specs:
        parts.append(
            fact.groupBy(label.alias("segment"), order.alias("sort_order"))
            .agg(
                F.count("*").alias("customers"),
                F.sum("defaulted").alias("defaults"),
                F.sum("credit_amount").alias("credit_amount"),
                # money actually lost on loans that defaulted (loan amount x loss given default)
                F.sum(F.col("credit_amount") * F.col("defaulted") * F.lit(LOSS_GIVEN_DEFAULT)).alias("estimated_loss"),
            )
            .withColumn("dimension", F.lit(dimension))
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.unionByName(part)
    return result.toPandas()


def segment_statistics(counts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Adds rates, confidence intervals and tests to the segment counts."""
    rows, dimension_rows = [], []
    for dimension, group in counts.groupby("dimension", sort=False):
        total_customers, total_defaults = group["customers"].sum(), group["defaults"].sum()
        portfolio_rate = total_defaults / total_customers
        for seg in group.itertuples():
            low, high = stats.wilson_interval(int(seg.defaults), int(seg.customers))
            rest_customers = total_customers - seg.customers
            rest_defaults = total_defaults - seg.defaults
            # Compare each segment with all other customers of the same dimension.
            test = (
                stats.two_proportion_test(
                    int(seg.defaults), int(seg.customers), int(rest_defaults), int(rest_customers)
                )
                if rest_customers > 0 and seg.customers > 0
                else None
            )
            rows.append(
                {
                    "dimension": dimension,
                    "segment": seg.segment,
                    "sort_order": int(seg.sort_order),
                    "customers": int(seg.customers),
                    "share_of_customers": seg.customers / total_customers,
                    "defaults": int(seg.defaults),
                    "default_rate": seg.defaults / seg.customers,
                    "ci_low": low,
                    "ci_high": high,
                    # how many times the portfolio average (1.0 = average risk)
                    "risk_index": (seg.defaults / seg.customers) / portfolio_rate,
                    "relative_risk_vs_rest": test.relative_risk if test else None,
                    "p_value_vs_rest": test.p_value if test else None,
                    "credit_amount": float(seg.credit_amount),
                    "estimated_loss": float(seg.estimated_loss),
                }
            )
        chi2, p_value, dof, cramers_v = stats.chi_square_test(group["defaults"].tolist(), group["customers"].tolist())
        iv = stats.information_value(group["defaults"].tolist(), group["customers"].tolist())
        dimension_rows.append(
            {
                "dimension": dimension,
                "segments": len(group),
                "information_value": iv,
                "predictive_power": _predictive_power(iv),
                "chi_square": chi2,
                "degrees_of_freedom": dof,
                "p_value": p_value,
                "cramers_v": cramers_v,
                "significant": p_value < ALPHA,
                # gender is analysed only to monitor fairness; it is never used to decide
                "use": "fairness monitoring only" if dimension == "gender" else "risk analysis",
            }
        )
    segments = pd.DataFrame(rows)
    # Correct the p-values for the number of segments tested at once.
    tested = segments["p_value_vs_rest"].notna()
    segments.loc[tested, "q_value"] = stats.benjamini_hochberg(segments.loc[tested, "p_value_vs_rest"].tolist())
    segments["significant"] = segments["q_value"] < ALPHA
    dimensions = pd.DataFrame(dimension_rows).sort_values("information_value", ascending=False)
    return segments, dimensions


def _predictive_power(iv: float) -> str:
    """Usual credit-market reading of the Information Value."""
    if iv >= 0.3:
        return "strong"
    if iv >= 0.1:
        return "medium"
    if iv >= 0.02:
        return "weak"
    return "not useful"


def hypothesis_tests(spark: SparkSession, fact: DataFrame) -> pd.DataFrame:
    """Answers each business question with a two-proportion test."""
    fact.createOrReplaceTempView("fact_application_labels")
    rows = []
    for h in HYPOTHESES:
        counts = spark.sql(
            f"""
            SELECT
                SUM(CASE WHEN {h.group_a} THEN 1 ELSE 0 END)         AS customers_a,
                SUM(CASE WHEN {h.group_a} THEN defaulted ELSE 0 END) AS defaults_a,
                SUM(CASE WHEN {h.group_b} THEN 1 ELSE 0 END)         AS customers_b,
                SUM(CASE WHEN {h.group_b} THEN defaulted ELSE 0 END) AS defaults_b
            FROM fact_application_labels
            """
        ).first()
        test = stats.two_proportion_test(counts.defaults_a, counts.customers_a, counts.defaults_b, counts.customers_b)
        rows.append(
            {
                "question": h.question,
                "group_a": h.group_a,
                "group_b": h.group_b,
                "customers_a": counts.customers_a,
                "customers_b": counts.customers_b,
                "default_rate_a": test.rate_a,
                "default_rate_b": test.rate_b,
                "difference_pp": test.difference * 100,
                "difference_ci_low_pp": test.ci_low * 100,
                "difference_ci_high_pp": test.ci_high * 100,
                "relative_risk": test.relative_risk,
                "z": test.z,
                "p_value": test.p_value,
            }
        )
    result = pd.DataFrame(rows)
    result["q_value"] = stats.benjamini_hochberg(result["p_value"].tolist())
    result["conclusion"] = result.apply(_conclusion, axis=1)
    # Confirmed questions first, strongest effects first (relative risk far from 1 in either direction).
    order = result.assign(
        _confirmed=result["q_value"] < ALPHA,
        _strength=result["relative_risk"].map(lambda rr: abs(np.log(rr)) if rr > 0 else 0),
    )
    return order.sort_values(["_confirmed", "_strength"], ascending=False).drop(columns=["_confirmed", "_strength"])


def _conclusion(row: pd.Series) -> str:
    """One sentence a business reader can quote."""
    if row["q_value"] >= ALPHA:
        return (
            f"Not confirmed: {row['default_rate_a']:.1%} vs {row['default_rate_b']:.1%}; the difference may be chance."
        )
    direction = "more" if row["relative_risk"] > 1 else "less"
    times = row["relative_risk"] if row["relative_risk"] > 1 else 1 / row["relative_risk"]
    return (
        f"Confirmed: {row['default_rate_a']:.1%} vs {row['default_rate_b']:.1%} "
        f"({times:.1f}x {direction} likely to default), statistically significant."
    )


def build_analysis(spark: SparkSession, storage: Storage) -> dict[str, int]:
    fact = fact_with_labels(spark, storage)
    segments, dimensions = segment_statistics(segment_counts(fact))
    hypotheses = hypothesis_tests(spark, fact)
    outputs = {
        "agg_default_by_segment": segments,
        "stats_dimension_tests": dimensions,
        "stats_hypothesis_tests": hypotheses,
    }
    for table, frame in outputs.items():
        write_table(spark, storage, from_pandas(spark, frame), "gold", table)
    return {table: len(frame) for table, frame in outputs.items()}
