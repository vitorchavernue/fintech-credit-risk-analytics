-- =====================================================================================
-- gold.dim_bureau_status — Situation of the customer's loans at other institutions (credit bureau).
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (0, 'No bureau record', 1),
    (1, 'Clean record', 2),
    (2, 'Overdue now', 3),
    (3, 'Bad debt or sold to collection', 4)
AS t(bureau_status_key, bureau_status, sort_order)
