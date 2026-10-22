# Findings — credit risk analysis

Portfolio: **307,511 granted loans**, default rate **8.07%**. Model and policy results are measured on the 30% of customers kept aside (never seen by the model).

## 1. Business questions (hypothesis tests)

| Question | Group A | Group B | Relative risk | q-value | Conclusion |
|---|---|---|---|---|---|
| Customers in the worst-rated regions default more than those in the best-rated regions | 11.4% | 4.8% | 2.36x | < 1e-16 | Confirmed: 11.4% vs 4.8% (2.4x more likely to default), statistically significant. |
| Customers with loans overdue now at other institutions default more than those with a clean record | 16.2% | 7.6% | 2.14x | < 1e-16 | Confirmed: 16.2% vs 7.6% (2.1x more likely to default), statistically significant. |
| Customers with higher education default less than those without it | 5.3% | 9.0% | 0.60x | < 1e-16 | Confirmed: 5.3% vs 9.0% (1.7x less likely to default), statistically significant. |
| Customers without a reported job (mostly pensioners) default less than employed customers | 5.4% | 8.7% | 0.62x | < 1e-16 | Confirmed: 5.4% vs 8.7% (1.6x less likely to default), statistically significant. |
| Customers already refused by Home Credit default more than those never refused | 10.4% | 7.1% | 1.47x | < 1e-16 | Confirmed: 10.4% vs 7.1% (1.5x more likely to default), statistically significant. |
| Customers who paid earlier installments late default more than those who always paid on time | 9.4% | 6.8% | 1.39x | < 1e-16 | Confirmed: 9.4% vs 6.8% (1.4x more likely to default), statistically significant. |
| Customers committing 30% or more of their income to the loan default more | 8.2% | 8.1% | 1.01x | 6.0e-01 | Not confirmed: 8.2% vs 8.1%; the difference may be chance. |

## 2. Which characteristics separate good and bad customers most

Information Value (IV) is the credit market's standard measure: below 0.02 not useful, 0.02-0.1 weak, 0.1-0.3 medium, above 0.3 strong. The chi-square test confirms the differences are not chance. Gender is shown for fairness monitoring only.

| Characteristic | Segments | Information Value | Predictive power | Cramér's V | Chi-square p-value |
|---|---|---|---|---|---|
| age band | 5 | 0.081 | weak | 0.077 | < 1e-16 |
| income type | 8 | 0.058 | weak | 0.064 | < 1e-16 |
| previous refusals | 4 | 0.053 | weak | 0.066 | < 1e-16 |
| payment behavior | 4 | 0.051 | weak | 0.064 | < 1e-16 |
| region rating | 3 | 0.051 | weak | 0.061 | < 1e-16 |
| education level | 5 | 0.051 | weak | 0.058 | < 1e-16 |
| gender | 3 | 0.039 | weak | 0.055 | < 1e-16 |
| bureau status | 4 | 0.024 | weak | 0.046 | < 1e-16 |
| housing type | 6 | 0.016 | not useful | 0.037 | < 1e-16 |
| contract type | 2 | 0.015 | not useful | 0.031 | < 1e-16 |
| income band | 5 | 0.010 | not useful | 0.026 | < 1e-16 |
| payment burden | 5 | 0.004 | not useful | 0.018 | < 1e-16 |

## 3. Credit score quality (unseen customers)

- **AUC 0.755 | Gini 0.509 | KS 0.383** (training: AUC 0.751 — similar values mean the model is not memorising)
- The 10% lowest scores hold **32.9%** of all defaults; the 30% lowest hold **65.2%**.
- Default rate goes from **26.5%** in the lowest band to **1.4%** in the highest.

Main factors (weights on a common scale):

| Factor | Effect | Odds ratio per typical step |
|---|---|---|
| External bureau score 3 (higher = safer) | reduces risk | 0.66 |
| External bureau score 2 (higher = safer) | reduces risk | 0.68 |
| External bureau score 1 (higher = safer) | reduces risk | 0.80 |
| Active loans at other institutions | increases risk | 1.20 |
| Years in the current job | reduces risk | 0.84 |
| Earlier requests refused | increases risk | 1.17 |
| Loan amount / price of the goods financed | increases risk | 1.17 |
| Annual payment / annual income (payment burden) | increases risk | 1.17 |
| Share of earlier installments paid late | increases risk | 1.16 |
| Loans reported by the credit bureau | reduces risk | 0.87 |

## 4. Approval cutoff

Assumptions: loss given default 45%, net margin on good loans 10%.

| Approval rate | Minimum score | Default rate approved | Defaults avoided | Net benefit | Recommended |
|---|---|---|---|---|---|
| 50% | 569 | 2.9% | 82% | -759.0 M |  |
| 56% | 565 | 3.2% | 77% | -545.3 M |  |
| 60% | 562 | 3.5% | 74% | -409.9 M |  |
| 66% | 558 | 3.7% | 70% | -219.1 M |  |
| 71% | 554 | 4.0% | 65% | -72.2 M |  |
| 75% | 550 | 4.4% | 59% | 43.0 M |  |
| 80% | 545 | 4.8% | 52% | 152.4 M |  |
| 85% | 539 | 5.4% | 43% | 201.9 M |  |
| 90% | 532 | 6.0% | 33% | 215.2 M | ⭐ |
| 95% | 521 | 6.8% | 19% | 178.5 M |  |
| 100% |  | 8.0% | 0% | 0.0 M |  |

**Recommended:** approve scores ≥ **532** (approval 90%): avoids 33% of defaults, default rate of approved loans 6.0% vs 8.0% approving everybody.

## 5. Champion vs challenger (offline experiment, random 50/50 split)

| Policy | Applications | Approval rate | Default rate approved | Loss per 1,000 approved loans |
|---|---|---|---|---|
| champion (current rules) | 45,746 | 72.9% | 7.13% | 17.4 M |
| challenger (credit score) | 46,190 | 74.0% | 4.15% | 11.6 M |

Default rate of the challenger minus the champion: **-2.98 pp** (-42% relative) (95% CI -3.33 to -2.63 pp), p-value < 1e-16 → **statistically significant**. A live A/B test would need about **1,289 applications per arm** to confirm it (80% power, 5% significance).

## 6. Fairness check at the recommended cutoff (gender is not used by the model)

| Gender | Approval rate | Default rate approved | Approval ratio vs highest |
|---|---|---|---|
| F | 92.0% | 5.3% | 1.00 |
| M | 86.6% | 7.4% | 0.94 |

Four-fifths rule: a ratio below 0.80 signals possible adverse impact and requires review.

## Limitations

- Only granted loans have an outcome, so results describe customers similar to those approved in the past.
- Money values use the dataset's currency and the assumptions above; they show orders of magnitude.
- The champion/challenger comparison is an offline simulation on historical outcomes, not a live experiment.
