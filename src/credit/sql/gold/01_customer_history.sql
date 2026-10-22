-- =====================================================================================
-- gold.customer_history — the customer's credit history, one row per loan application
--
-- Summarises, for each applicant, three sources of past behaviour:
--   1. other institutions (credit bureau): how many loans, any overdue, any bad debt;
--   2. earlier requests to Home Credit: how many, how many refused;
--   3. installments of earlier Home Credit loans: how often paid late or not paid.
-- These are the facts a credit analyst checks before approving a loan.
-- =====================================================================================

-- 1. Credit bureau: loans at other institutions ---------------------------------------
WITH bureau AS (
    SELECT
        application_id,
        COUNT(*)                                                          AS bureau_credits,
        SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END)                AS bureau_active_credits,
        -- "overdue now": an active loan with days or amounts past due today
        SUM(CASE WHEN status = 'Active' AND (days_overdue > 0 OR amount_overdue > 0)
                 THEN 1 ELSE 0 END)                                       AS bureau_overdue_credits,
        -- loans written off as bad debt or sold to a collection agency
        SUM(CASE WHEN status IN ('Bad debt', 'Sold') THEN 1 ELSE 0 END)   AS bureau_bad_debt_credits,
        -- amounts are only added up in the main currency ("currency 1", 99.9% of records),
        -- because the source does not convert the other currencies
        SUM(CASE WHEN status = 'Active' AND currency = 'currency 1'
                 THEN outstanding_debt ELSE 0 END)                        AS bureau_outstanding_debt
    FROM silver_bureau_credits
    GROUP BY application_id
),

-- 2. Earlier requests to Home Credit ---------------------------------------------------
previous AS (
    SELECT
        application_id,
        COUNT(*)                                                          AS previous_applications,
        SUM(CASE WHEN decision = 'Approved' THEN 1 ELSE 0 END)            AS previous_approved,
        SUM(CASE WHEN decision = 'Refused'  THEN 1 ELSE 0 END)            AS previous_refused
    FROM silver_previous_applications
    GROUP BY application_id
),

-- 3. Installments of earlier Home Credit loans -----------------------------------------
installments AS (
    SELECT
        application_id,
        COUNT(*)                                                          AS installments_due,
        SUM(CASE WHEN paid_late OR never_paid THEN 1 ELSE 0 END)          AS installments_late,
        SUM(CASE WHEN never_paid THEN 1 ELSE 0 END)                       AS installments_not_paid,
        SUM(CASE WHEN underpaid THEN 1 ELSE 0 END)                        AS installments_underpaid,
        MAX(days_late)                                                    AS max_days_late
    FROM silver_installment_payments
    GROUP BY application_id
)

-- One row per application. Customers with no history get zeros (they have none),
-- never a missing value, so totals in the reports always add up.
SELECT
    a.application_id,
    COALESCE(b.bureau_credits, 0)                                         AS bureau_credits,
    COALESCE(b.bureau_active_credits, 0)                                  AS bureau_active_credits,
    COALESCE(b.bureau_overdue_credits, 0)                                 AS bureau_overdue_credits,
    COALESCE(b.bureau_bad_debt_credits, 0)                                AS bureau_bad_debt_credits,
    COALESCE(b.bureau_outstanding_debt, 0)                                AS bureau_outstanding_debt,
    COALESCE(p.previous_applications, 0)                                  AS previous_applications,
    COALESCE(p.previous_approved, 0)                                      AS previous_approved,
    COALESCE(p.previous_refused, 0)                                       AS previous_refused,
    COALESCE(i.installments_due, 0)                                       AS installments_due,
    COALESCE(i.installments_late, 0)                                      AS installments_late,
    COALESCE(i.installments_not_paid, 0)                                  AS installments_not_paid,
    COALESCE(i.installments_underpaid, 0)                                 AS installments_underpaid,
    COALESCE(i.max_days_late, 0)                                          AS max_days_late,
    -- share of past installments paid late or not paid (empty when there is no history)
    ROUND(i.installments_late / i.installments_due, 4)                    AS late_installment_share
FROM silver_applications a
LEFT JOIN bureau       b ON b.application_id = a.application_id
LEFT JOIN previous     p ON p.application_id = a.application_id
LEFT JOIN installments i ON i.application_id = a.application_id
