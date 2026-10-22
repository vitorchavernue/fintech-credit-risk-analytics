# Databricks notebook source
# MAGIC %md
# MAGIC # Credit risk — exploration notebook
# MAGIC
# MAGIC Business questions answered with **Spark SQL** on the gold tables produced by the
# MAGIC `credit-risk-pipeline` job. Each cell is a question a credit or payments manager would ask.
# MAGIC Use the chart button under each result to visualise it.

# COMMAND ----------

# Catalog where the job saved the tables (Free Edition default: "workspace").
dbutils.widgets.text("catalog", "workspace")  # noqa: F821 (dbutils exists in Databricks)
gold = f"{dbutils.widgets.get('catalog')}.credit_gold"  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1. How large is the portfolio and how many customers defaulted?

# COMMAND ----------

display(  # noqa: F821
    spark.sql(f"""
        SELECT COUNT(*)                         AS applications,
               SUM(defaulted)                   AS defaults,
               ROUND(AVG(defaulted) * 100, 2)   AS default_rate_pct,
               ROUND(SUM(credit_amount) / 1e9, 2) AS credit_billions
        FROM {gold}.fact_application
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2. Does past payment behaviour predict default?
# MAGIC Default rate with its 95% confidence interval, by how the customer paid earlier installments.

# COMMAND ----------

display(  # noqa: F821
    spark.sql(f"""
        SELECT segment                              AS payment_behavior,
               customers,
               ROUND(default_rate * 100, 2)          AS default_rate_pct,
               ROUND(ci_low * 100, 2)                AS ci_low_pct,
               ROUND(ci_high * 100, 2)               AS ci_high_pct,
               ROUND(risk_index, 2)                  AS times_portfolio_average
        FROM {gold}.agg_default_by_segment
        WHERE dimension = 'payment_behavior'
        ORDER BY sort_order
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3. Business hypotheses — confirmed or not?

# COMMAND ----------

display(spark.sql(f"SELECT question, conclusion, q_value FROM {gold}.stats_hypothesis_tests"))  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4. Does the credit score separate good and bad customers?
# MAGIC Default rate by score band (1 = lowest scores) on customers the model never saw.

# COMMAND ----------

display(  # noqa: F821
    spark.sql(f"""
        SELECT score_band, min_score, max_score, customers,
               ROUND(default_rate * 100, 2)                  AS default_rate_pct,
               ROUND(cumulative_share_of_defaults * 100, 1)  AS pct_of_all_defaults_up_to_band
        FROM {gold}.agg_score_bands
        ORDER BY score_band
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5. Where should the approval cutoff be?

# COMMAND ----------

display(  # noqa: F821
    spark.sql(f"""
        SELECT ROUND(approval_rate * 100) AS approval_rate_pct,
               minimum_score,
               ROUND(default_rate_approved * 100, 2) AS default_rate_approved_pct,
               ROUND(share_of_defaults_avoided * 100, 1) AS pct_defaults_avoided,
               ROUND(net_benefit / 1e6, 1) AS net_benefit_millions,
               recommended
        FROM {gold}.policy_cutoff_simulation
        ORDER BY approval_rate
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 6. Champion (current rules) vs challenger (credit score)

# COMMAND ----------

display(spark.table(f"{gold}.policy_champion_challenger"))  # noqa: F821
