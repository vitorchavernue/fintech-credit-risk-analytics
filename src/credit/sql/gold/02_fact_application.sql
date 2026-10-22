-- =====================================================================================
-- gold.fact_application — central table of the star schema (one row per application)
--
-- Joins the application with the customer's credit history and places each customer
-- in the business segments used by the reports (age band, income band, payment
-- behaviour...). Each segment key points to a small dimension table with the label
-- and the display order, so Power BI shows the bands in the right order.
-- The band limits below must match the dimension tables (03_ to 09_ files);
-- the data quality checks fail if any key has no matching dimension row.
-- =====================================================================================
SELECT
    a.application_id,
    a.defaulted,
    a.contract_type,
    a.gender,
    a.income_type,
    a.education,
    a.family_status,
    a.housing_type,
    a.occupation,
    a.employer_type,
    a.region_rating,
    a.owns_car,
    a.owns_property,
    a.children_count,
    a.age_years,
    a.years_employed,
    a.employment_not_reported,
    a.annual_income,
    a.credit_amount,
    a.annual_payment,
    a.goods_price,
    a.credit_to_income,
    a.payment_to_income,
    a.credit_to_goods_price,
    a.external_score_1,
    a.external_score_2,
    a.external_score_3,
    h.bureau_credits,
    h.bureau_active_credits,
    h.bureau_overdue_credits,
    h.bureau_bad_debt_credits,
    h.bureau_outstanding_debt,
    h.previous_applications,
    h.previous_approved,
    h.previous_refused,
    h.installments_due,
    h.installments_late,
    h.installments_not_paid,
    h.installments_underpaid,
    h.max_days_late,
    h.late_installment_share,

    -- Education level, ordered from basic to highest -----------------------------------
    CASE a.education
        WHEN 'Lower secondary'               THEN 1
        WHEN 'Secondary / secondary special' THEN 2
        WHEN 'Incomplete higher'             THEN 3
        WHEN 'Higher education'              THEN 4
        WHEN 'Academic degree'               THEN 5
        ELSE 0                                         -- not informed
    END AS education_key,

    -- Age band --------------------------------------------------------------------------
    CASE
        WHEN a.age_years < 25 THEN 1
        WHEN a.age_years < 35 THEN 2
        WHEN a.age_years < 45 THEN 3
        WHEN a.age_years < 55 THEN 4
        ELSE 5
    END AS age_band_key,

    -- Annual income band ------------------------------------------------------------------
    CASE
        WHEN a.annual_income < 100000 THEN 1
        WHEN a.annual_income < 150000 THEN 2
        WHEN a.annual_income < 200000 THEN 3
        WHEN a.annual_income < 300000 THEN 4
        ELSE 5
    END AS income_band_key,

    -- Payment burden: share of yearly income that goes to this loan's payments -----------
    CASE
        WHEN a.payment_to_income IS NULL THEN 0       -- payment not informed
        WHEN a.payment_to_income < 0.10  THEN 1
        WHEN a.payment_to_income < 0.20  THEN 2
        WHEN a.payment_to_income < 0.30  THEN 3
        ELSE 4
    END AS payment_burden_key,

    -- How the customer paid earlier Home Credit installments -----------------------------
    CASE
        WHEN h.installments_due = 0            THEN 0   -- no earlier loan with Home Credit
        WHEN h.installments_late = 0           THEN 1   -- always on time
        WHEN h.late_installment_share <= 0.10  THEN 2   -- occasionally late (up to 10%)
        ELSE 3                                          -- frequently late (more than 10%)
    END AS payment_behavior_key,

    -- Situation at other institutions (credit bureau); the worst situation prevails -----
    CASE
        WHEN h.bureau_credits = 0              THEN 0   -- unknown to the bureau
        WHEN h.bureau_bad_debt_credits > 0     THEN 3   -- bad debt or sold to collection
        WHEN h.bureau_overdue_credits > 0      THEN 2   -- overdue now
        ELSE 1                                          -- clean record
    END AS bureau_status_key,

    -- Earlier requests refused by Home Credit ---------------------------------------------
    CASE
        WHEN h.previous_applications = 0       THEN 0   -- first request
        WHEN h.previous_refused = 0            THEN 1   -- never refused
        WHEN h.previous_refused = 1            THEN 2   -- refused once
        ELSE 3                                          -- refused two or more times
    END AS previous_refusals_key
FROM silver_applications a
JOIN gold_customer_history h ON h.application_id = a.application_id
