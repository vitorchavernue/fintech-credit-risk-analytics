"""Data quality gate: checks that run after the gold layer is built.

"Critical" checks stop the pipeline (wrong numbers must never reach the reports).
"Info" checks only record facts worth knowing about the data (e.g. how many customers
have no employment date). Results go to ``gold.dq_results`` and ``reports/data_quality.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from credit.analysis import DIMENSIONS
from credit.config import Storage
from credit.spark import from_pandas, read_table, write_table


@dataclass
class Check:
    name: str
    severity: str  # "critical" or "info"
    passed: bool
    detail: str


class QualityGateError(RuntimeError):
    """Raised when a critical check fails: the data is not released."""


def run_checks(spark: SparkSession, storage: Storage) -> list[Check]:
    bronze = read_table(spark, storage, "bronze", "applications")
    apps = read_table(spark, storage, "silver", "applications")
    fact = read_table(spark, storage, "gold", "fact_application")
    bureau = read_table(spark, storage, "silver", "bureau_credits")
    installments = read_table(spark, storage, "silver", "installment_payments")
    checks: list[Check] = []

    # 1. No application lost or duplicated between the source file and the reports.
    n_bronze, n_silver, n_fact = bronze.count(), apps.count(), fact.count()
    checks.append(
        Check(
            "Every application of the source file reaches the reports",
            "critical",
            n_bronze == n_silver == n_fact,
            f"source {n_bronze:,} · silver {n_silver:,} · gold {n_fact:,}",
        )
    )
    duplicates = n_silver - apps.select("application_id").distinct().count()
    checks.append(Check("Application id is unique", "critical", duplicates == 0, f"{duplicates} duplicates"))

    # 2. The outcome (defaulted) is always 0 or 1, and no default is lost on the way to gold.
    invalid_outcome = apps.where(~F.col("defaulted").isin(0, 1) | F.col("defaulted").isNull()).count()
    checks.append(Check("Outcome is 0 or 1", "critical", invalid_outcome == 0, f"{invalid_outcome} invalid"))
    defaults_silver = apps.agg(F.sum("defaulted")).first()[0]
    defaults_gold = fact.agg(F.sum("defaulted")).first()[0]
    checks.append(
        Check(
            "Number of defaults is the same in silver and gold",
            "critical",
            defaults_silver == defaults_gold,
            f"silver {defaults_silver:,} · gold {defaults_gold:,}",
        )
    )

    # 3. Amounts and scores within valid ranges.
    bad_amounts = apps.where((F.col("credit_amount") <= 0) | (F.col("annual_income") <= 0)).count()
    checks.append(Check("Loan amount and income are positive", "critical", bad_amounts == 0, f"{bad_amounts} rows"))
    out_of_range = apps.where(
        " OR ".join(f"external_score_{i} < 0 OR external_score_{i} > 1" for i in (1, 2, 3))
    ).count()
    checks.append(Check("External scores between 0 and 1", "critical", out_of_range == 0, f"{out_of_range} rows"))

    # 4. Every segment key of the fact table exists in its dimension (star schema integrity).
    for name, key in DIMENSIONS.items():
        dim = read_table(spark, storage, "gold", f"dim_{name}")
        orphans = fact.join(dim, key, "left_anti").count()
        checks.append(
            Check(f"Every {key} exists in dim_{name}", "critical", orphans == 0, f"{orphans} rows without a match")
        )

    # 5. Facts worth knowing (do not stop the pipeline).
    linked = bureau.join(apps.select("application_id"), "application_id", "left_semi").count()
    total_bureau = bureau.count()
    checks.append(
        Check(
            "Bureau records linked to an application in this file",
            "info",
            True,
            f"{linked / total_bureau:.1%} of {total_bureau:,} "
            "(the rest belong to Kaggle's test customers, which have no outcome)",
        )
    )
    not_reported = apps.where("employment_not_reported").count()
    checks.append(
        Check(
            "Employment date not reported (code 365243)",
            "info",
            True,
            f"{not_reported:,} customers ({not_reported / n_silver:.1%}), treated as 'not reported'",
        )
    )
    never_paid = installments.where("never_paid").count()
    checks.append(Check("Earlier installments never paid", "info", True, f"{never_paid:,} of {installments.count():,}"))
    return checks


def write_report(checks: list[Check], path: Path) -> None:
    lines = ["# Data quality report", "", "| Check | Severity | Result | Detail |", "|---|---|---|---|"]
    for c in checks:
        result = "✅ pass" if c.passed else "❌ FAIL"
        lines.append(f"| {c.name} | {c.severity} | {result} | {c.detail} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_quality(spark: SparkSession, storage: Storage, report: Path = Path("reports/data_quality.md")) -> dict:
    checks = run_checks(spark, storage)
    frame = pd.DataFrame([c.__dict__ for c in checks])
    write_table(spark, storage, from_pandas(spark, frame), "gold", "dq_results")
    write_report(checks, report)
    failed = [c.name for c in checks if c.severity == "critical" and not c.passed]
    if failed:
        raise QualityGateError(f"Critical data quality checks failed: {failed}")
    return {"checks": len(checks), "failed": 0}
