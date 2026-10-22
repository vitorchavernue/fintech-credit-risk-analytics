-- =====================================================================================
-- gold.dim_payment_burden — Share of the yearly income committed to this loan's payments.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (0, 'Not informed', 1),
    (1, 'Under 10%', 2),
    (2, '10%-20%', 3),
    (3, '20%-30%', 4),
    (4, '30% or more', 5)
AS t(payment_burden_key, payment_burden, sort_order)
