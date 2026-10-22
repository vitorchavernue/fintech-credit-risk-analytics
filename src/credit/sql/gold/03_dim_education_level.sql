-- =====================================================================================
-- gold.dim_education_level — Education level of the applicant, ordered from basic to highest.
-- Small reference table: the label shown in the reports and the display order.
-- The keys must match the CASE rules in 02_fact_application.sql.
-- =====================================================================================
SELECT * FROM VALUES
    (0, 'Not informed', 1),
    (1, 'Lower secondary', 2),
    (2, 'Secondary', 3),
    (3, 'Incomplete higher', 4),
    (4, 'Higher education', 5),
    (5, 'Academic degree', 6)
AS t(education_key, education_level, sort_order)
