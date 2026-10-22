"""Exports the gold tables used by the Power BI report as single Parquet files.

Power BI Desktop reads one Parquet file per table from a local folder (parameter
``DataFolder`` of the semantic model). On Databricks, Power BI connects to the Unity
Catalog tables instead, so this export is only needed for the local report.

Usage:
    python scripts/export_powerbi.py --out powerbi/data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from credit.config import Storage  # noqa: E402
from credit.spark import get_spark, read_table  # noqa: E402

# Only the columns the report uses, to keep the model small and fast.
FACT_COLUMNS = [
    "application_id", "defaulted", "sample", "credit_score", "probability_of_default", "risk_grade",
    "contract_type", "gender", "income_type", "housing_type", "occupation", "region_rating",
    "credit_amount", "annual_income", "annual_payment", "payment_to_income", "credit_to_income", "age_years",
    "employment_not_reported", "bureau_credits", "bureau_overdue_credits", "previous_applications",
    "previous_refused", "installments_due", "late_installment_share",
    "education_key", "age_band_key", "income_band_key", "payment_burden_key", "payment_behavior_key",
    "bureau_status_key", "previous_refusals_key",
]  # fmt: skip

TABLES = {
    "fact_application_scored": FACT_COLUMNS,
    "dim_education_level": None,
    "dim_age_band": None,
    "dim_income_band": None,
    "dim_payment_burden": None,
    "dim_payment_behavior": None,
    "dim_bureau_status": None,
    "dim_previous_refusals": None,
    "dim_risk_grade": None,
    "stats_hypothesis_tests": None,
    "stats_dimension_tests": None,
    "model_performance": None,
    "model_drivers": None,
    "agg_score_bands": None,
    "policy_cutoff_simulation": None,
    "policy_champion_challenger": None,
    "policy_fairness_check": None,
    "dq_results": None,
}


def main(out: Path) -> None:
    storage = Storage.from_env()
    spark = get_spark(storage)
    out.mkdir(parents=True, exist_ok=True)
    for table, columns in TABLES.items():
        df = read_table(spark, storage, "gold", table)
        frame = (df.select(*columns) if columns else df).toPandas()
        # Plain text type (not "large string"), the one every Power BI version reads.
        data = pa.Table.from_pandas(frame, preserve_index=False)
        schema = pa.schema(
            [pa.field(f.name, pa.string() if pa.types.is_large_string(f.type) else f.type) for f in data.schema]
        )
        pq.write_table(data.cast(schema), out / f"{table}.parquet", compression="snappy")
        print(f"{table}: {len(frame):,} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("powerbi/data"))
    main(parser.parse_args().out)
