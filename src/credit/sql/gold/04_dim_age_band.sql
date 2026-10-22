-- =====================================================================================
-- gold.dim_age_band — Age of the applicant on the application date.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (1, 'Under 25', 1),
    (2, '25-34', 2),
    (3, '35-44', 3),
    (4, '45-54', 4),
    (5, '55 or more', 5)
AS t(age_band_key, age_band, sort_order)
