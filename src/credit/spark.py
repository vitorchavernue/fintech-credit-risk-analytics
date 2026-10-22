"""Spark session and table read/write helpers used by every layer.

On Databricks the session already exists and tables go to Unity Catalog.
Locally (and in CI) a Spark session is started on the machine and tables are saved
as folders, in Delta format (same as Databricks) or Parquet when Delta is not available.
"""

from __future__ import annotations

import os
import sys

from pyspark.sql import DataFrame, SparkSession

from credit.config import Storage


def get_spark(storage: Storage, app_name: str = "credit-risk-analytics") -> SparkSession:
    # Inside Databricks (notebook or job, classic or serverless): use the platform session.
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:
        return SparkSession.builder.getOrCreate()
    active = SparkSession.getActiveSession()
    if active is not None:
        return active

    # Local machine / CI: start Spark using all CPU cores, without the web console,
    # with the worker processes running the same Python as this program.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    builder = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", os.environ.get("CREDIT_SPARK_MEMORY", "4g"))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "16")
        # lets Spark hand tables to pandas quickly (Arrow) on recent Java versions
        .config("spark.driver.extraJavaOptions", "-Dio.netty.tryReflectionSetAccessible=true")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )
    # Delta Lake (the table format of Databricks) needs two extra settings and its library.
    if storage.table_format == "delta":
        from delta import configure_spark_with_delta_pip

        builder = configure_spark_with_delta_pip(
            builder.config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension").config(
                "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
            )
        )
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def write_table(spark: SparkSession, storage: Storage, df: DataFrame, layer: str, table: str) -> None:
    """Saves a table, fully replacing the previous version (every run rebuilds the layer)."""
    writer = df.write.mode("overwrite").option("overwriteSchema", "true")
    if storage.catalog:
        # Databricks: managed table in Unity Catalog (schema created on the first run).
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {storage.catalog}.credit_{layer}")
        writer.saveAsTable(storage.table_name(layer, table))
    else:
        writer.format(storage.table_format).save(storage.path(layer, table))


def read_table(spark: SparkSession, storage: Storage, layer: str, table: str) -> DataFrame:
    if storage.catalog:
        return spark.table(storage.table_name(layer, table))
    return spark.read.format(storage.table_format).load(storage.path(layer, table))


def from_pandas(spark: SparkSession, frame) -> DataFrame:
    """Converts a small pandas result table to Spark, turning missing values into real nulls
    (so Power BI shows them as blank instead of "NaN")."""
    import math

    def clean(value):
        return None if isinstance(value, float) and (math.isnan(value) or math.isinf(value)) else value

    # Large tables (e.g. one score per customer) have no missing values: use the fast path.
    if len(frame) > 10_000:
        try:
            spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")
        except Exception:  # Databricks serverless manages this setting itself (Arrow is always on)
            pass
        return spark.createDataFrame(frame)

    records = [{key: clean(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]
    # Keep the column order of the result table.
    return spark.createDataFrame(records).select(*[str(column) for column in frame.columns])
