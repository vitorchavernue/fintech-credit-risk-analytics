"""Credit policy: where to set the approval cutoff, and does the new score beat the
current rules? Everything is measured on the 30% of customers the model never saw.

1. Cutoff simulation: for approval rates from 50% to 100%, how many bad customers are
   avoided, how many good customers are lost, and the money involved:
     loss avoided  = loans of rejected bad customers x loss given default
     margin lost   = loans of rejected good customers x net margin
     net benefit   = loss avoided - margin lost   (compared with approving everybody)

2. Champion vs challenger (offline experiment): the test customers are split at random
   into two equal arms. Arm A follows the current rule-based policy ("champion");
   arm B follows the new score ("challenger") at the SAME approval rate, so the only
   difference is how customers are chosen. A two-proportion test says whether the
   challenger's lower default rate is real, and a sample-size calculation says how many
   applications a live A/B test would need to confirm it.

Limitation stated in the reports: the data only contains loans that were granted, so
results describe customers similar to those approved in the past.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from credit import stats
from credit.config import ALPHA, LOSS_GIVEN_DEFAULT, NET_MARGIN, SEED, Storage
from credit.spark import from_pandas, read_table, write_table

# Current rule-based policy (champion): typical "knock-out" rules of a credit desk.
# A customer is rejected if ANY rule applies.
CHAMPION_RULES = {
    "loan overdue now, written off or sold to collection at another institution": "bureau_status_key IN (2, 3)",
    "refused three or more times before": "previous_refused >= 3",
    "late on more than 30% of earlier installments": "COALESCE(late_installment_share, 0) > 0.30",
    "payment takes 30% or more of yearly income": "payment_burden_key = 4",
}


def load_test_customers(spark: SparkSession, storage: Storage) -> pd.DataFrame:
    """Test customers with their score, loan amount and the champion decision."""
    rejected_by_rules = " OR ".join(f"({rule})" for rule in CHAMPION_RULES.values())
    return (
        read_table(spark, storage, "gold", "fact_application_scored")
        .where(F.col("sample") == "test")
        .select(
            "application_id",
            "defaulted",
            "credit_amount",
            "credit_score",
            "gender",
            # a customer with no matching rule is approved
            F.expr(f"NOT COALESCE({rejected_by_rules}, false)").alias("champion_approves"),
        )
        .toPandas()
    )


def money(customers: pd.DataFrame) -> tuple[float, float]:
    """Loss that defaulted loans cause, and margin that good loans produce."""
    bad = customers["defaulted"] == 1
    loss = float(customers.loc[bad, "credit_amount"].sum() * LOSS_GIVEN_DEFAULT)
    margin = float(customers.loc[~bad, "credit_amount"].sum() * NET_MARGIN)
    return loss, margin


def cutoff_simulation(customers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total_defaults = customers["defaulted"].sum()
    for approval_rate in np.arange(0.50, 1.0001, 0.05):
        # Approve the customers with the highest scores until the approval rate is reached.
        cutoff = float(np.quantile(customers["credit_score"], 1 - approval_rate)) if approval_rate < 1 else -np.inf
        approved = customers[customers["credit_score"] >= cutoff]
        rejected = customers[customers["credit_score"] < cutoff]
        loss_avoided, margin_lost = money(rejected)
        rows.append(
            {
                "target_approval_rate": round(float(approval_rate), 2),
                "minimum_score": None if approval_rate >= 1 else cutoff,
                "approved": len(approved),
                "approval_rate": len(approved) / len(customers),
                "default_rate_approved": approved["defaulted"].mean(),
                "default_rate_rejected": rejected["defaulted"].mean() if len(rejected) else None,
                "defaults_avoided": int(rejected["defaulted"].sum()),
                "share_of_defaults_avoided": rejected["defaulted"].sum() / total_defaults,
                "good_customers_rejected": int((rejected["defaulted"] == 0).sum()),
                "credit_approved": float(approved["credit_amount"].sum()),
                "loss_avoided": loss_avoided,
                "margin_lost": margin_lost,
                "net_benefit": loss_avoided - margin_lost,
            }
        )
    result = pd.DataFrame(rows)
    # The recommended cutoff is the one with the highest net benefit.
    result["recommended"] = result["net_benefit"] == result["net_benefit"].max()
    return result


def champion_challenger(customers: pd.DataFrame) -> pd.DataFrame:
    # Random 50/50 split of the test customers (fixed seed: same arms in every run).
    rng = np.random.default_rng(SEED)
    arm = np.where(rng.random(len(customers)) < 0.5, "A", "B")
    champion, challenger = customers[arm == "A"].copy(), customers[arm == "B"].copy()

    # Arm A: current rules. Arm B: new score, approving the same share of customers.
    champion["approved"] = champion["champion_approves"]
    approval_rate = champion["approved"].mean()
    cutoff = np.quantile(challenger["credit_score"], 1 - approval_rate)
    challenger["approved"] = challenger["credit_score"] >= cutoff

    rows = []
    for name, group in (("champion (current rules)", champion), ("challenger (credit score)", challenger)):
        approved = group[group["approved"]]
        loss, _ = money(approved)
        rows.append(
            {
                "policy": name,
                "applications": len(group),
                "approved": len(approved),
                "approval_rate": len(approved) / len(group),
                "defaults_approved": int(approved["defaulted"].sum()),
                "default_rate_approved": approved["defaulted"].mean(),
                "loss_per_1000_approved": loss / len(approved) * 1000,
                "minimum_score": float(cutoff) if name.startswith("challenger") else None,
            }
        )
    result = pd.DataFrame(rows)

    # Is the challenger's default rate really different? (two-proportion z-test)
    a, b = result.iloc[0], result.iloc[1]
    test = stats.two_proportion_test(
        int(b["defaults_approved"]), int(b["approved"]), int(a["defaults_approved"]), int(a["approved"])
    )
    # Approved customers per arm a live A/B test would need to detect this difference
    # with 80% power at 5% significance, converted into applications.
    approved_needed = stats.sample_size_two_proportions(a["default_rate_approved"], b["default_rate_approved"])
    result["difference_pp"] = test.difference * 100
    result["difference_ci_low_pp"] = test.ci_low * 100
    result["difference_ci_high_pp"] = test.ci_high * 100
    result["relative_change"] = test.relative_risk - 1
    result["p_value"] = test.p_value
    result["significant"] = test.p_value < ALPHA
    result["live_test_applications_per_arm"] = int(np.ceil(approved_needed / approval_rate))
    return result


def fairness_check(customers: pd.DataFrame, minimum_score: float) -> pd.DataFrame:
    """At the recommended cutoff: approval and default rates by gender.
    Gender is not used by the model; this check confirms the result is still fair."""
    customers = customers.assign(approved=customers["credit_score"] >= minimum_score)
    rows = []
    for gender, group in customers.dropna(subset=["gender"]).groupby("gender"):
        approved = group[group["approved"]]
        rows.append(
            {
                "gender": gender,
                "applications": len(group),
                "approval_rate": group["approved"].mean(),
                "default_rate_approved": approved["defaulted"].mean(),
            }
        )
    result = pd.DataFrame(rows)
    # Four-fifths rule: the lower approval rate should be at least 80% of the higher one.
    result["approval_ratio_vs_highest"] = result["approval_rate"] / result["approval_rate"].max()
    return result


def build_policy(spark: SparkSession, storage: Storage) -> dict[str, int]:
    customers = load_test_customers(spark, storage)
    cutoffs = cutoff_simulation(customers)
    recommended = cutoffs.loc[cutoffs["recommended"], "minimum_score"].iloc[0]
    outputs = {
        "policy_cutoff_simulation": cutoffs,
        "policy_champion_challenger": champion_challenger(customers),
        "policy_fairness_check": fairness_check(customers, recommended if recommended is not None else -np.inf),
    }
    for table, frame in outputs.items():
        write_table(spark, storage, from_pandas(spark, frame), "gold", table)
    return {table: len(frame) for table, frame in outputs.items()}
