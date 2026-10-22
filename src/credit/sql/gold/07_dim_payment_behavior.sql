-- =====================================================================================
-- gold.dim_payment_behavior — How the customer paid the installments of earlier Home Credit loans.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (0, 'No earlier loan', 1),
    (1, 'Always on time', 2),
    (2, 'Occasionally late (up to 10%)', 3),
    (3, 'Frequently late (over 10%)', 4)
AS t(payment_behavior_key, payment_behavior, sort_order)
