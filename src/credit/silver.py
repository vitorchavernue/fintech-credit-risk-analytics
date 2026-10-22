"""Silver layer: clean, typed and business-friendly versions of each source.

What happens here, in plain words:
* columns get clear names (``AMT_CREDIT`` -> ``credit_amount``) and the right data types;
* source-system codes that are not real values are turned into "unknown"
  (e.g. employment date 365243 = "not reported");
* technical duplicates are removed;
* installments paid in several parts are combined into one row per installment.
No business rule that changes the meaning of the data is applied here.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

from credit.config import EMPLOYMENT_NOT_REPORTED, Storage
from credit.spark import read_table, write_table


def _int(name: str) -> Column:
    return F.col(name).cast("int")


def _amount(name: str) -> Column:
    return F.col(name).cast("double")


def _years_ago(days_column: str) -> Column:
    """The source stores dates as 'days before the application' (negative numbers)."""
    return F.round(-F.col(days_column).cast("double") / 365.25, 1)


def clean_applications(bronze: DataFrame) -> DataFrame:
    """One row per loan application, with the outcome: did the customer default?"""
    days_employed = F.col("DAYS_EMPLOYED").cast("int")
    df = bronze.select(
        _int("SK_ID_CURR").alias("application_id"),
        # 1 = the customer had payment difficulties (defaulted), 0 = paid normally
        _int("TARGET").alias("defaulted"),
        F.col("NAME_CONTRACT_TYPE").alias("contract_type"),
        # Gender is kept only to monitor fairness; it is never used to score customers.
        F.when(F.col("CODE_GENDER").isin("M", "F"), F.col("CODE_GENDER")).alias("gender"),
        (F.col("FLAG_OWN_CAR") == "Y").alias("owns_car"),
        (F.col("FLAG_OWN_REALTY") == "Y").alias("owns_property"),
        _int("CNT_CHILDREN").alias("children_count"),
        _amount("AMT_INCOME_TOTAL").alias("annual_income"),
        _amount("AMT_CREDIT").alias("credit_amount"),
        _amount("AMT_ANNUITY").alias("annual_payment"),
        _amount("AMT_GOODS_PRICE").alias("goods_price"),
        F.col("NAME_INCOME_TYPE").alias("income_type"),
        F.col("NAME_EDUCATION_TYPE").alias("education"),
        F.col("NAME_FAMILY_STATUS").alias("family_status"),
        F.col("NAME_HOUSING_TYPE").alias("housing_type"),
        F.coalesce(F.col("OCCUPATION_TYPE"), F.lit("Not informed")).alias("occupation"),
        F.col("ORGANIZATION_TYPE").alias("employer_type"),
        # Region risk rating defined by the lender: 1 = best regions, 3 = worst
        _int("REGION_RATING_CLIENT_W_CITY").alias("region_rating"),
        _years_ago("DAYS_BIRTH").alias("age_years"),
        # 365243 means "employment not reported" (mostly pensioners), not 1,000 years of work
        F.when(days_employed == EMPLOYMENT_NOT_REPORTED, None)
        .otherwise(F.round(-days_employed / 365.25, 1))
        .alias("years_employed"),
        (days_employed == EMPLOYMENT_NOT_REPORTED).alias("employment_not_reported"),
        # Scores from external credit bureaus (0 = riskiest, 1 = safest); may be missing
        _amount("EXT_SOURCE_1").alias("external_score_1"),
        _amount("EXT_SOURCE_2").alias("external_score_2"),
        _amount("EXT_SOURCE_3").alias("external_score_3"),
    )
    return (
        df.where(F.col("application_id").isNotNull())
        .dropDuplicates(["application_id"])
        # Affordability indicators used by credit analysts:
        .withColumn("credit_to_income", F.round(F.col("credit_amount") / F.col("annual_income"), 4))
        # share of the yearly income committed to this loan's payments
        .withColumn("payment_to_income", F.round(F.col("annual_payment") / F.col("annual_income"), 4))
        # loan amount compared with the price of the goods being financed
        .withColumn("credit_to_goods_price", F.round(F.col("credit_amount") / F.col("goods_price"), 4))
    )


def clean_bureau_credits(bronze: DataFrame) -> DataFrame:
    """Loans the customer has (or had) at other institutions, as reported by the credit bureau."""
    return (
        bronze.select(
            _int("SK_ID_CURR").alias("application_id"),
            _int("SK_ID_BUREAU").alias("bureau_credit_id"),
            F.col("CREDIT_ACTIVE").alias("status"),  # Active, Closed, Sold (to collection) or Bad debt
            F.col("CREDIT_CURRENCY").alias("currency"),
            F.col("CREDIT_TYPE").alias("credit_type"),
            _years_ago("DAYS_CREDIT").alias("years_since_opened"),
            F.coalesce(_int("CREDIT_DAY_OVERDUE"), F.lit(0)).alias("days_overdue"),
            F.coalesce(_amount("AMT_CREDIT_SUM_OVERDUE"), F.lit(0.0)).alias("amount_overdue"),
            _amount("AMT_CREDIT_MAX_OVERDUE").alias("max_amount_overdue"),
            _amount("AMT_CREDIT_SUM").alias("credit_amount"),
            # Some bureau records show negative debt (credit balance); that is not debt.
            F.greatest(_amount("AMT_CREDIT_SUM_DEBT"), F.lit(0.0)).alias("outstanding_debt"),
            _int("CNT_CREDIT_PROLONG").alias("times_extended"),
        )
        .where(F.col("bureau_credit_id").isNotNull())
        .dropDuplicates(["bureau_credit_id"])
    )


def clean_previous_applications(bronze: DataFrame) -> DataFrame:
    """Earlier requests of the same customer to Home Credit and the decision taken."""
    return (
        bronze
        # The source repeats some requests for technical reasons; keep only the final
        # version of each contract and the last request of each day, as the data dictionary advises.
        .where((F.col("FLAG_LAST_APPL_PER_CONTRACT") == "Y") & (_int("NFLAG_LAST_APPL_IN_DAY") == 1))
        .select(
            _int("SK_ID_PREV").alias("previous_application_id"),
            _int("SK_ID_CURR").alias("application_id"),
            F.col("NAME_CONTRACT_TYPE").alias("contract_type"),
            F.col("NAME_CONTRACT_STATUS").alias("decision"),  # Approved, Refused, Canceled, Unused offer
            F.col("CODE_REJECT_REASON").alias("reject_reason"),
            _amount("AMT_APPLICATION").alias("amount_requested"),
            _amount("AMT_CREDIT").alias("amount_granted"),
            _years_ago("DAYS_DECISION").alias("years_since_decision"),
        )
        .where(F.col("previous_application_id").isNotNull())
        .dropDuplicates(["previous_application_id"])
    )


def clean_installments(bronze: DataFrame) -> DataFrame:
    """One row per installment of earlier Home Credit loans: was it paid on time and in full?

    The source has one row per PAYMENT; an installment paid in two parts appears twice.
    Here the parts are added up, and the installment counts as paid on the day of the last part.
    """
    payments = bronze.select(
        _int("SK_ID_PREV").alias("previous_application_id"),
        _int("SK_ID_CURR").alias("application_id"),
        F.col("NUM_INSTALMENT_VERSION").cast("double").alias("installment_version"),
        _int("NUM_INSTALMENT_NUMBER").alias("installment_number"),
        F.col("DAYS_INSTALMENT").cast("double").alias("due_day"),
        F.col("DAYS_ENTRY_PAYMENT").cast("double").alias("paid_day"),
        _amount("AMT_INSTALMENT").alias("amount_due"),
        _amount("AMT_PAYMENT").alias("amount_paid"),
    )
    keys = ["previous_application_id", "application_id", "installment_version", "installment_number"]
    installments = payments.groupBy(*keys).agg(
        F.max("due_day").alias("due_day"),
        F.max("amount_due").alias("amount_due"),
        F.coalesce(F.sum("amount_paid"), F.lit(0.0)).alias("amount_paid"),
        F.max("paid_day").alias("last_paid_day"),
    )
    return (
        installments
        # Days between the due date and the payment (0 when paid on or before the due date).
        .withColumn("days_late", F.greatest(F.col("last_paid_day") - F.col("due_day"), F.lit(0.0)))
        .withColumn("paid_late", F.col("days_late") > 0)
        # No payment date at all: the installment was never paid.
        .withColumn("never_paid", F.col("last_paid_day").isNull())
        # Paid less than due (1 unit of tolerance for rounding).
        .withColumn("underpaid", F.col("amount_paid") < F.col("amount_due") - 1)
        .drop("last_paid_day")
    )


SILVER_BUILDERS = {
    "applications": clean_applications,
    "bureau_credits": clean_bureau_credits,
    "previous_applications": clean_previous_applications,
    "installment_payments": clean_installments,
}


def build_silver(spark: SparkSession, storage: Storage) -> dict[str, int]:
    """Cleans every bronze table into its silver table and returns the row counts."""
    counts: dict[str, int] = {}
    for table, builder in SILVER_BUILDERS.items():
        write_table(spark, storage, builder(read_table(spark, storage, "bronze", table)), "silver", table)
        counts[table] = read_table(spark, storage, "silver", table).count()
    return counts
