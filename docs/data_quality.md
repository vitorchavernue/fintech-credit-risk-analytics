# Data quality report

| Check | Severity | Result | Detail |
|---|---|---|---|
| Every application of the source file reaches the reports | critical | ✅ pass | source 307,511 · silver 307,511 · gold 307,511 |
| Application id is unique | critical | ✅ pass | 0 duplicates |
| Outcome is 0 or 1 | critical | ✅ pass | 0 invalid |
| Number of defaults is the same in silver and gold | critical | ✅ pass | silver 24,825 · gold 24,825 |
| Loan amount and income are positive | critical | ✅ pass | 0 rows |
| External scores between 0 and 1 | critical | ✅ pass | 0 rows |
| Every payment_behavior_key exists in dim_payment_behavior | critical | ✅ pass | 0 rows without a match |
| Every bureau_status_key exists in dim_bureau_status | critical | ✅ pass | 0 rows without a match |
| Every previous_refusals_key exists in dim_previous_refusals | critical | ✅ pass | 0 rows without a match |
| Every payment_burden_key exists in dim_payment_burden | critical | ✅ pass | 0 rows without a match |
| Every age_band_key exists in dim_age_band | critical | ✅ pass | 0 rows without a match |
| Every income_band_key exists in dim_income_band | critical | ✅ pass | 0 rows without a match |
| Every education_key exists in dim_education_level | critical | ✅ pass | 0 rows without a match |
| Bureau records linked to an application in this file | info | ✅ pass | 85.4% of 1,716,428 (the rest belong to Kaggle's test customers, which have no outcome) |
| Employment date not reported (code 365243) | info | ✅ pass | 55,374 customers (18.0%), treated as 'not reported' |
| Earlier installments never paid | info | ✅ pass | 2,905 of 12,951,918 |
