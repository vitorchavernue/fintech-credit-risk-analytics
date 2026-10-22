"""Credit scorecard: estimates each applicant's probability of default and turns it into
a credit score (higher = safer), as used by credit committees.

Method, in plain words:
1. 70% of the customers are used to learn the pattern; the other 30% are kept aside and
   used only to measure how good the score is on customers it has never seen.
2. A logistic regression (the standard model in credit risk, because every factor's
   effect can be explained) is trained with Spark MLlib, so it scales to millions of rows.
3. The probability is converted to the usual score scale (600 points = 50 good customers
   per bad one; +20 points = odds doubled) and to risk grades A (best) to E (worst).

Fairness and governance: gender and family status are NOT used by the model.

Outputs (gold layer): ``fact_credit_score``, ``dim_risk_grade``, ``model_performance``,
``model_drivers``, ``agg_score_bands`` and ``fact_application_scored`` (for Power BI).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.feature import Imputer, OneHotEncoder, StandardScaler, StringIndexer, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from credit import stats
from credit.config import (
    SCORE_BASE_ODDS,
    SCORE_BASE_POINTS,
    SCORE_POINTS_TO_DOUBLE_ODDS,
    TEST_SHARE,
    Storage,
)
from credit.spark import from_pandas, read_table, write_table

# Factors the model may use, with the plain-language meaning shown in the reports.
NUMERIC_FEATURES = {
    "external_score_1": "External bureau score 1 (higher = safer)",
    "external_score_2": "External bureau score 2 (higher = safer)",
    "external_score_3": "External bureau score 3 (higher = safer)",
    "external_score_1_missing": "External bureau score 1 not available",
    "external_score_3_missing": "External bureau score 3 not available",
    "age_years": "Age of the applicant",
    "years_employed": "Years in the current job",
    "employment_not_reported": "Employment not reported (mostly pensioners)",
    "log_income": "Annual income (log scale)",
    "credit_to_income": "Loan amount / annual income",
    "payment_to_income": "Annual payment / annual income (payment burden)",
    "credit_to_goods_price": "Loan amount / price of the goods financed",
    "region_rating": "Region risk rating (1 best, 3 worst)",
    "owns_car_flag": "Owns a car",
    "owns_property_flag": "Owns a property",
    "bureau_credits": "Loans reported by the credit bureau",
    "bureau_active_credits": "Active loans at other institutions",
    "bureau_overdue_credits": "Loans overdue now at other institutions",
    "bureau_bad_debt_credits": "Loans written off or sold to collection",
    "log_bureau_debt": "Debt at other institutions (log scale)",
    "previous_applications": "Earlier requests to Home Credit",
    "previous_refused": "Earlier requests refused",
    "late_installment_share_filled": "Share of earlier installments paid late",
    "installments_not_paid": "Earlier installments never paid",
    "max_days_late": "Longest delay on an earlier installment (days)",
    "no_installment_history": "No earlier Home Credit loan",
}
CATEGORICAL_FEATURES = {
    "contract_type": "Contract type",
    "education": "Education level",
    "income_type": "Income type",
    "housing_type": "Housing situation",
    "occupation": "Occupation",
}
# Business explanation of each grade, shown in the reports.
GRADES = {
    "A": "Very low risk",
    "B": "Low risk",
    "C": "Moderate risk",
    "D": "High risk",
    "E": "Very high risk",
}


def model_input(fact: DataFrame) -> DataFrame:
    """Prepares the factors: flags as numbers, money on a log scale, missing-value markers,
    and the fixed train/test split (by customer id, so it never changes between runs)."""
    return (
        fact.withColumn("external_score_1_missing", F.col("external_score_1").isNull().cast("double"))
        .withColumn("external_score_3_missing", F.col("external_score_3").isNull().cast("double"))
        .withColumn("employment_not_reported", F.col("employment_not_reported").cast("double"))
        .withColumn("owns_car_flag", F.col("owns_car").cast("double"))
        .withColumn("owns_property_flag", F.col("owns_property").cast("double"))
        # Money varies over a huge range; the log scale stops a few very high incomes
        # from dominating the model.
        .withColumn("log_income", F.log1p("annual_income"))
        .withColumn("log_bureau_debt", F.log1p("bureau_outstanding_debt"))
        # Customers with no earlier loan have no late share: mark them and use 0.
        .withColumn("no_installment_history", (F.col("installments_due") == 0).cast("double"))
        .withColumn("late_installment_share_filled", F.coalesce("late_installment_share", F.lit(0.0)))
        # 30% of customers (chosen by a fixed hash of the id) are kept aside for testing.
        .withColumn(
            "sample",
            F.when(F.abs(F.hash("application_id")) % 100 < int(TEST_SHARE * 100), "test").otherwise("train"),
        )
        .select(
            "application_id",
            "defaulted",
            "sample",
            *[F.col(c).cast("double").alias(c) for c in NUMERIC_FEATURES],
            *CATEGORICAL_FEATURES,
        )
    )


def build_pipeline() -> Pipeline:
    numeric = list(NUMERIC_FEATURES)
    imputed = [f"{c}_imputed" for c in numeric]
    categorical = list(CATEGORICAL_FEATURES)
    return Pipeline(
        stages=[
            # Missing numbers (e.g. years employed of pensioners) get the typical (median) value.
            Imputer(inputCols=numeric, outputCols=imputed, strategy="median"),
            # Text categories become yes/no columns; unseen categories are handled safely.
            StringIndexer(
                inputCols=categorical,
                outputCols=[f"{c}_index" for c in categorical],
                handleInvalid="keep",
                stringOrderType="frequencyDesc",
            ),
            OneHotEncoder(
                inputCols=[f"{c}_index" for c in categorical],
                outputCols=[f"{c}_vector" for c in categorical],
                handleInvalid="keep",
            ),
            VectorAssembler(inputCols=imputed + [f"{c}_vector" for c in categorical], outputCol="raw_features"),
            # Same scale for every factor, so their weights can be compared with each other.
            StandardScaler(inputCol="raw_features", outputCol="features", withMean=True, withStd=True),
            # Small penalty keeps the weights stable when factors are related to each other.
            LogisticRegression(featuresCol="features", labelCol="defaulted", regParam=0.001, maxIter=200),
        ]
    )


def probability_to_score(probability: np.ndarray | float) -> np.ndarray | float:
    """Market score scale: 600 points at odds of 50 good : 1 bad, +20 points doubles the odds."""
    factor = SCORE_POINTS_TO_DOUBLE_ODDS / math.log(2)
    offset = SCORE_BASE_POINTS - factor * math.log(SCORE_BASE_ODDS)
    p = np.clip(probability, 1e-6, 1 - 1e-6)
    return np.round(offset + factor * np.log((1 - p) / p), 0)


def model_drivers(model, scored: DataFrame) -> pd.DataFrame:
    """Weight of each factor, translated into business language."""
    attrs = scored.schema["raw_features"].metadata["ml_attr"]["attrs"]
    names = {a["idx"]: a["name"] for group in attrs.values() for a in group}
    coefficients = model.stages[-1].coefficients.toArray()
    labels = {**{f"{k}_imputed": v for k, v in NUMERIC_FEATURES.items()}}
    rows = []
    for idx, coefficient in enumerate(coefficients):
        raw = names[idx]
        if raw in labels:
            factor, detail = labels[raw], ""
        else:  # one yes/no column per category, named "<column>_vector_<category>"
            column, _, category = raw.partition("_vector_")
            factor, detail = CATEGORICAL_FEATURES.get(column, column), category
        rows.append(
            {
                "factor": factor,
                "category": detail,
                "coefficient": float(coefficient),
                # change in the odds of default for one "typical step" (1 standard deviation)
                "odds_ratio_per_std": math.exp(coefficient),
                "effect": "increases risk" if coefficient > 0 else "reduces risk",
                "importance": abs(float(coefficient)),
            }
        )
    drivers = pd.DataFrame(rows).sort_values("importance", ascending=False)
    drivers["rank"] = range(1, len(drivers) + 1)
    return drivers


def risk_grades(train_scores: np.ndarray) -> pd.DataFrame:
    """Five grades of the same size on the training customers: A = best 20% scores."""
    cuts = np.quantile(train_scores, [0.2, 0.4, 0.6, 0.8])
    bounds = [-np.inf, *cuts, np.inf]
    rows = []
    for i, grade in enumerate(["E", "D", "C", "B", "A"]):
        rows.append(
            {
                "risk_grade": grade,
                "description": GRADES[grade],
                "min_score": None if i == 0 else float(bounds[i]),
                "max_score": None if i == 4 else float(bounds[i + 1]),
                "sort_order": 5 - i,
            }
        )
    return pd.DataFrame(rows).sort_values("sort_order")


def assign_grade(scores: np.ndarray, grades: pd.DataFrame) -> np.ndarray:
    cuts = grades.sort_values("sort_order", ascending=False)["max_score"].dropna().to_numpy()  # E, D, C, B limits
    return np.array(["E", "D", "C", "B", "A"])[np.searchsorted(cuts, scores, side="right")]


def score_bands(scored: pd.DataFrame) -> pd.DataFrame:
    """Test customers split into 10 equal score bands (1 = lowest scores): how many bad
    customers each band holds and how many are caught by rejecting the lowest bands."""
    test = scored[scored["sample"] == "test"].copy()
    test["score_band"] = pd.qcut(test["credit_score"].rank(method="first"), 10, labels=range(1, 11)).astype(int)
    bands = (
        test.groupby("score_band")
        .agg(
            min_score=("credit_score", "min"),
            max_score=("credit_score", "max"),
            customers=("application_id", "count"),
            defaults=("defaulted", "sum"),
            avg_probability_of_default=("probability_of_default", "mean"),
        )
        .reset_index()
    )
    bands["default_rate"] = bands["defaults"] / bands["customers"]
    # Share of all bad customers found in this band and the bands below it.
    bands["cumulative_share_of_defaults"] = bands["defaults"].cumsum() / bands["defaults"].sum()
    bands["cumulative_share_of_customers"] = bands["customers"].cumsum() / bands["customers"].sum()
    return bands


def build_scorecard(spark: SparkSession, storage: Storage) -> dict[str, int]:
    fact = read_table(spark, storage, "gold", "fact_application")
    # (no .cache(): not available on Databricks serverless; the input is cheap to recompute)
    data = model_input(fact)
    train = data.where(F.col("sample") == "train")

    # 1. Learn the pattern on the training customers only.
    model = build_pipeline().fit(train)
    scored_spark = model.transform(data)
    scored = (
        scored_spark.select(
            "application_id",
            "defaulted",
            "sample",
            vector_to_array("probability")[1].alias("probability_of_default"),
        )
        .toPandas()
        .sort_values("application_id")
    )

    # 2. Probability -> score -> grade (grade limits come from training customers only).
    scored["credit_score"] = probability_to_score(scored["probability_of_default"].to_numpy())
    grades = risk_grades(scored.loc[scored["sample"] == "train", "credit_score"].to_numpy())
    scored["risk_grade"] = assign_grade(scored["credit_score"].to_numpy(), grades)

    # 3. How good is the score? Measured separately on training and on unseen (test) customers.
    performance = []
    for sample, part in scored.groupby("sample"):
        auc = stats.roc_auc(part["probability_of_default"], part["defaulted"])
        performance.append(
            {
                "sample": sample,
                "customers": len(part),
                "defaults": int(part["defaulted"].sum()),
                "default_rate": part["defaulted"].mean(),
                "auc": auc,
                "gini": 2 * auc - 1,  # market convention: Gini = 2 x AUC - 1
                "ks": stats.ks_statistic(part["probability_of_default"], part["defaulted"]),
            }
        )

    outputs = {
        "fact_credit_score": scored,
        "dim_risk_grade": grades,
        "model_performance": pd.DataFrame(performance),
        "model_drivers": model_drivers(model, scored_spark),
        "agg_score_bands": score_bands(scored),
    }
    for table, frame in outputs.items():
        write_table(spark, storage, from_pandas(spark, frame), "gold", table)

    # 4. Table used by Power BI: every application with its score and grade.
    scores = read_table(spark, storage, "gold", "fact_credit_score").drop("defaulted")
    write_table(spark, storage, fact.join(scores, "application_id", "left"), "gold", "fact_application_scored")
    return {table: len(frame) for table, frame in outputs.items()}
