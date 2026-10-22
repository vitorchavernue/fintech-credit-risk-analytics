"""Bronze layer: an exact copy of the source files, stored as tables.

Every column is kept as text, exactly as received. Nothing is filtered or corrected here,
so any number in the reports can always be traced back to the original file.
Two control columns are added: the file each row came from and when it was loaded.
"""

from __future__ import annotations

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from credit.config import SOURCE_FILES, Storage
from credit.spark import read_table, write_table


def build_bronze(spark: SparkSession, storage: Storage) -> dict[str, int]:
    """Loads each source file into its bronze table and returns the row count of each one."""
    counts: dict[str, int] = {}
    for table in SOURCE_FILES:
        df = (
            spark.read.option("header", True)
            # Read everything as text: types are decided in the silver layer, never here.
            .option("inferSchema", False)
            .csv(storage.raw_file(table))
            # Lineage: which file each row came from and when it entered the platform.
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.current_timestamp())
        )
        write_table(spark, storage, df, "bronze", table)
        # Count from the saved table (fast) instead of reading the large file again.
        counts[table] = read_table(spark, storage, "bronze", table).count()
    return counts
