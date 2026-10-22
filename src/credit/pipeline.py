"""Runs the platform end to end, or one step at a time.

Steps, in order:
  bronze    -> copy of the source files
  silver    -> clean, typed tables
  gold      -> star schema for Power BI (Spark SQL)
  quality   -> data quality gate (stops the run if a critical check fails)
  analysis  -> default rates by segment and hypothesis tests
  scorecard -> credit score model and risk grades
  policy    -> approval cutoff, champion vs challenger, fairness check
  report    -> reports/findings.md

Usage:
    python -m credit.pipeline --step all
    python -m credit.pipeline --step scorecard
On Databricks each step is a task of the job defined in databricks.yml.
"""

from __future__ import annotations

import argparse
import os
import time

from credit.analysis import build_analysis
from credit.bronze import build_bronze
from credit.config import Storage
from credit.gold import build_gold
from credit.policy import build_policy
from credit.quality import build_quality
from credit.report import build_report
from credit.scorecard import build_scorecard
from credit.silver import build_silver
from credit.spark import get_spark

STEPS = {
    "bronze": build_bronze,
    "silver": build_silver,
    "gold": build_gold,
    "quality": build_quality,
    "analysis": build_analysis,
    "scorecard": build_scorecard,
    "policy": build_policy,
    "report": build_report,
}


def run(step: str = "all") -> None:
    storage = Storage.from_env()
    spark = get_spark(storage)
    for name in STEPS if step == "all" else [step]:
        started = time.time()
        result = STEPS[name](spark, storage)
        print(f"[{name}] {result} ({time.time() - started:.0f}s)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Credit risk analytics pipeline")
    parser.add_argument("--step", choices=["all", *STEPS], default="all")
    # Databricks jobs pass these as parameters (serverless jobs have no environment variables).
    parser.add_argument("--catalog", help="Unity Catalog catalog (Databricks); tables go to <catalog>.credit_<layer>")
    parser.add_argument("--raw-dir", help="folder or Unity Catalog volume with the Home Credit files")
    args = parser.parse_args()
    if args.catalog:
        os.environ["CREDIT_CATALOG"] = args.catalog
    if args.raw_dir:
        os.environ["CREDIT_RAW_DIR"] = args.raw_dir
    run(args.step)


if __name__ == "__main__":
    main()
