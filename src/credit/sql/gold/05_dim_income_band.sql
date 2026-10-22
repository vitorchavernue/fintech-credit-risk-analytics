-- =====================================================================================
-- gold.dim_income_band — Declared annual income.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (1, 'Under 100k', 1),
    (2, '100k-150k', 2),
    (3, '150k-200k', 3),
    (4, '200k-300k', 4),
    (5, '300k or more', 5)
AS t(income_band_key, income_band, sort_order)
