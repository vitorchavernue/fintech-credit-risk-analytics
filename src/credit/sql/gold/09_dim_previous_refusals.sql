-- =====================================================================================
-- gold.dim_previous_refusals — Earlier requests of the customer refused by Home Credit.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (0, 'First request', 1),
    (1, 'Never refused', 2),
    (2, 'Refused once', 3),
    (3, 'Refused 2+ times', 4)
AS t(previous_refusals_key, previous_refusals, sort_order)
