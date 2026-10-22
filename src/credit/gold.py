"""Gold layer: business tables built with Spark SQL (star schema for Power BI).

The rules live in plain SQL files (``src/credit/sql/gold``), so analysts can read and review them
without knowing Python. They run in file-name order; each file creates the table with
the same name (``02_fact_application.sql`` -> ``gold.fact_application``), which later
files can use as ``gold_<name>``.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession

from credit.config import SOURCE_FILES, Storage
from credit.spark import read_table, write_table

# Kept inside the package so the same files ship to Databricks with the code.
SQL_DIR = Path(__file__).resolve().parent / "sql" / "gold"


def gold_sql_files(sql_dir: Path = SQL_DIR) -> list[tuple[str, str]]:
    """Returns (table name, SQL text) for every gold file, in execution order."""
    return [(path.stem.split("_", 1)[1], path.read_text(encoding="utf-8")) for path in sorted(sql_dir.glob("*.sql"))]


def register_silver_views(spark: SparkSession, storage: Storage) -> None:
    """Makes the silver tables available to SQL as silver_<table>."""
    for table in SOURCE_FILES:
        read_table(spark, storage, "silver", table).createOrReplaceTempView(f"silver_{table}")


def build_gold(spark: SparkSession, storage: Storage, sql_dir: Path = SQL_DIR) -> dict[str, int]:
    register_silver_views(spark, storage)
    counts: dict[str, int] = {}
    for table, sql in gold_sql_files(sql_dir):
        write_table(spark, storage, spark.sql(sql), "gold", table)
        # The saved table becomes available to the next SQL files.
        saved = read_table(spark, storage, "gold", table)
        saved.createOrReplaceTempView(f"gold_{table}")
        counts[table] = saved.count()
    return counts
