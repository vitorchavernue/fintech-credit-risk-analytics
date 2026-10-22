"""Writes ``reports/findings.md``: the business conclusions of the run, generated from the
gold tables, so the written conclusions always match the data.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession

from credit.config import LOSS_GIVEN_DEFAULT, NET_MARGIN, Storage
from credit.spark import read_table


def _table(frame: pd.DataFrame) -> str:
    """Markdown table without extra dependencies."""
    header = "| " + " | ".join(frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def pvalue(value: float) -> str:
    """Very small p-values are shown as a limit (the computer rounds them to zero)."""
    return "< 1e-16" if value < 1e-16 else f"{value:.1e}"


def pct(value: float, digits: int = 1) -> str:
    return "" if pd.isna(value) else f"{value:.{digits}%}"


def build_report(spark: SparkSession, storage: Storage, path: Path = Path("reports/findings.md")) -> dict:
    def gold(table: str) -> pd.DataFrame:
        return read_table(spark, storage, "gold", table).toPandas()

    perf = gold("model_performance").set_index("sample")
    # confirmed questions first, strongest effects first
    hyp = gold("stats_hypothesis_tests")
    hyp = hyp.assign(_c=hyp["q_value"] < 0.05, _s=np.log(hyp["relative_risk"]).abs())
    hyp = hyp.sort_values(["_c", "_s"], ascending=False)
    dims = gold("stats_dimension_tests").sort_values("information_value", ascending=False)
    drivers = gold("model_drivers").sort_values("rank").head(10)
    bands = gold("agg_score_bands").sort_values("score_band")
    cutoffs = gold("policy_cutoff_simulation").sort_values("target_approval_rate")
    # champion first, then challenger
    cc = gold("policy_champion_challenger").sort_values("policy", key=lambda p: ~p.str.startswith("champion"))
    fair = gold("policy_fairness_check")
    rec = cutoffs[cutoffs["recommended"]].iloc[0]
    test = perf.loc["test"]

    lines = [
        "# Findings — credit risk analysis",
        "",
        f"Portfolio: **{int(perf['customers'].sum()):,} granted loans**, "
        f"default rate **{pct(perf['defaults'].sum() / perf['customers'].sum(), 2)}**. "
        "Model and policy results are measured on the 30% of customers kept aside (never seen by the model).",
        "",
        "## 1. Business questions (hypothesis tests)",
        "",
        _table(
            pd.DataFrame(
                {
                    "Question": hyp["question"],
                    "Group A": hyp["default_rate_a"].map(pct),
                    "Group B": hyp["default_rate_b"].map(pct),
                    "Relative risk": hyp["relative_risk"].map(lambda v: f"{v:.2f}x"),
                    "q-value": hyp["q_value"].map(pvalue),
                    "Conclusion": hyp["conclusion"],
                }
            )
        ),
        "",
        "## 2. Which characteristics separate good and bad customers most",
        "",
        "Information Value (IV) is the credit market's standard measure: below 0.02 not useful, "
        "0.02-0.1 weak, 0.1-0.3 medium, above 0.3 strong. The chi-square test confirms the differences are "
        "not chance. Gender is shown for fairness monitoring only.",
        "",
        _table(
            pd.DataFrame(
                {
                    "Characteristic": dims["dimension"].str.replace("_", " "),
                    "Segments": dims["segments"],
                    "Information Value": dims["information_value"].map(lambda v: f"{v:.3f}"),
                    "Predictive power": dims["predictive_power"],
                    "Cramér's V": dims["cramers_v"].map(lambda v: f"{v:.3f}"),
                    "Chi-square p-value": dims["p_value"].map(pvalue),
                }
            )
        ),
        "",
        "## 3. Credit score quality (unseen customers)",
        "",
        f"- **AUC {test['auc']:.3f} | Gini {test['gini']:.3f} | KS {test['ks']:.3f}** "
        f"(training: AUC {perf.loc['train', 'auc']:.3f} — similar values mean the model is not memorising)",
        f"- The 10% lowest scores hold **{pct(bands.iloc[0]['cumulative_share_of_defaults'])}** of all defaults; "
        f"the 30% lowest hold **{pct(bands.iloc[2]['cumulative_share_of_defaults'])}**.",
        f"- Default rate goes from **{pct(bands.iloc[0]['default_rate'])}** in the lowest band "
        f"to **{pct(bands.iloc[-1]['default_rate'])}** in the highest.",
        "",
        "Main factors (weights on a common scale):",
        "",
        _table(
            pd.DataFrame(
                {
                    "Factor": drivers["factor"] + drivers["category"].map(lambda c: f" = {c}" if c else ""),
                    "Effect": drivers["effect"],
                    "Odds ratio per typical step": drivers["odds_ratio_per_std"].map(lambda v: f"{v:.2f}"),
                }
            )
        ),
        "",
        "## 4. Approval cutoff",
        "",
        f"Assumptions: loss given default {LOSS_GIVEN_DEFAULT:.0%}, net margin on good loans {NET_MARGIN:.0%}.",
        "",
        _table(
            pd.DataFrame(
                {
                    "Approval rate": cutoffs["approval_rate"].map(lambda v: pct(v, 0)),
                    "Minimum score": cutoffs["minimum_score"].map(lambda v: "" if pd.isna(v) else f"{v:.0f}"),
                    "Default rate approved": cutoffs["default_rate_approved"].map(pct),
                    "Defaults avoided": cutoffs["share_of_defaults_avoided"].map(lambda v: pct(v, 0)),
                    "Net benefit": cutoffs["net_benefit"].map(lambda v: f"{v / 1e6:,.1f} M"),
                    "Recommended": cutoffs["recommended"].map(lambda v: "⭐" if v else ""),
                }
            )
        ),
        "",
        f"**Recommended:** approve scores ≥ **{rec['minimum_score']:.0f}** "
        f"(approval {pct(rec['approval_rate'], 0)}): avoids {pct(rec['share_of_defaults_avoided'], 0)} of defaults, "
        f"default rate of approved loans {pct(rec['default_rate_approved'])} "
        f"vs {pct(cutoffs.iloc[-1]['default_rate_approved'])} approving everybody.",
        "",
        "## 5. Champion vs challenger (offline experiment, random 50/50 split)",
        "",
        _table(
            pd.DataFrame(
                {
                    "Policy": cc["policy"],
                    "Applications": cc["applications"].map(lambda v: f"{v:,}"),
                    "Approval rate": cc["approval_rate"].map(pct),
                    "Default rate approved": cc["default_rate_approved"].map(lambda v: pct(v, 2)),
                    "Loss per 1,000 approved loans": cc["loss_per_1000_approved"].map(lambda v: f"{v / 1e6:,.1f} M"),
                }
            )
        ),
        "",
        f"Default rate of the challenger minus the champion: **{cc['difference_pp'].iloc[0]:+.2f} pp** "
        f"({cc['relative_change'].iloc[0]:+.0%} relative) "
        f"(95% CI {cc['difference_ci_low_pp'].iloc[0]:+.2f} to {cc['difference_ci_high_pp'].iloc[0]:+.2f} pp), "
        f"p-value {pvalue(cc['p_value'].iloc[0])} → "
        + ("**statistically significant**." if cc["significant"].iloc[0] else "not significant.")
        + f" A live A/B test would need about **{int(cc['live_test_applications_per_arm'].iloc[0]):,} applications "
        "per arm** to confirm it (80% power, 5% significance).",
        "",
        "## 6. Fairness check at the recommended cutoff (gender is not used by the model)",
        "",
        _table(
            pd.DataFrame(
                {
                    "Gender": fair["gender"],
                    "Approval rate": fair["approval_rate"].map(pct),
                    "Default rate approved": fair["default_rate_approved"].map(pct),
                    "Approval ratio vs highest": fair["approval_ratio_vs_highest"].map(lambda v: f"{v:.2f}"),
                }
            )
        ),
        "",
        "Four-fifths rule: a ratio below 0.80 signals possible adverse impact and requires review.",
        "",
        "## Limitations",
        "",
        "- Only granted loans have an outcome, so results describe customers similar to those approved in the past.",
        "- Money values use the dataset's currency and the assumptions above; they show orders of magnitude.",
        "- The champion/challenger comparison is an offline simulation on historical outcomes, not a live experiment.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(path)}
