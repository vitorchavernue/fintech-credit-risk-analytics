"""Draws the README charts from the gold tables (run after the pipeline).

Usage:
    python scripts/make_charts.py --out docs/images
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from credit.config import Storage  # noqa: E402
from credit.spark import get_spark, read_table  # noqa: E402

# One hue for magnitudes, a second hue only to tell two policies apart, gray for references.
BLUE, ORANGE, GRAY, INK, MUTED = "#2a78d6", "#eb6834", "#8a8984", "#0b0b0b", "#52514e"
plt.rcParams.update(
    {
        "font.size": 10,
        "axes.edgecolor": "#d0cfca",
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#ecebe7",
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
    }
)


def pct_axis(ax, axis="x", step=None):
    target = ax.xaxis if axis == "x" else ax.yaxis
    target.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    if step:
        target.set_major_locator(matplotlib.ticker.MultipleLocator(step))


def risk_drivers(segments, portfolio_rate, out: Path) -> None:
    """Default rate (with 95% confidence interval) by segment, four characteristics."""
    panels = [
        ("payment_behavior", "Earlier Home Credit installments"),
        ("previous_refusals", "Earlier requests to Home Credit"),
        ("bureau_status", "Loans at other institutions (bureau)"),
        ("age_band", "Age"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2))
    for ax, (dimension, title) in zip(axes.flat, panels, strict=True):
        data = segments[segments["dimension"] == dimension].sort_values("sort_order", ascending=False)
        y = np.arange(len(data))
        rate = data["default_rate"].to_numpy()
        err = [rate - data["ci_low"].to_numpy(), data["ci_high"].to_numpy() - rate]
        ax.barh(y, rate, height=0.55, color=BLUE, xerr=err, error_kw={"ecolor": INK, "lw": 1, "capsize": 3})
        ax.axvline(portfolio_rate, color=GRAY, ls="--", lw=1)
        ax.set_yticks(y, data["segment"])
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        pct_axis(ax, step=0.05)
        ax.grid(axis="y", visible=False)
        # value label placed after the confidence interval, so they never overlap
        for yi, r, high in zip(y, rate, data["ci_high"], strict=True):
            ax.text(high + 0.006, yi, f"{r:.1%}", va="center", fontsize=9, color=INK)
        ax.set_xlim(0, max(0.2, rate.max() + 0.05))
    fig.suptitle(
        "Default rate by segment — bars: 95% confidence interval; dashed line: portfolio average",
        x=0.01,
        ha="left",
        fontsize=12,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(out / "risk_drivers.png", dpi=150)
    plt.close(fig)


def score_quality(bands, out: Path) -> None:
    """Default rate by score band, and share of defaults caught by rejecting the lowest scores."""
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2))
    left.bar(bands["score_band"], bands["default_rate"], color=BLUE, width=0.6)
    for x, r in zip(bands["score_band"], bands["default_rate"], strict=True):
        left.text(x, r + 0.005, f"{r:.1%}", ha="center", fontsize=8, color=INK)
    left.set_xticks(bands["score_band"])
    left.set_xlabel("Score band (1 = lowest 10% of scores, 10 = highest)")
    left.set_title("Default rate by score band (unseen customers)", loc="left", fontsize=11, color=INK)
    pct_axis(left, "y")
    left.grid(axis="x", visible=False)

    share_customers = np.r_[0, bands["cumulative_share_of_customers"]]
    share_defaults = np.r_[0, bands["cumulative_share_of_defaults"]]
    right.plot(share_customers, share_defaults, color=BLUE, lw=2, marker="o", ms=4)
    right.plot([0, 1], [0, 1], color=GRAY, ls="--", lw=1)
    right.text(0.72, 0.64, "random selection", color=MUTED, fontsize=9, rotation=33)
    right.annotate(
        f"lowest 30% of scores\nhold {share_defaults[3]:.0%} of defaults",
        xy=(0.3, share_defaults[3]),
        xytext=(0.42, 0.22),
        fontsize=9,
        color=INK,
        arrowprops={"arrowstyle": "-", "color": MUTED},
    )
    right.set_xlabel("Customers with the lowest scores")
    right.set_ylabel("Share of all defaults")
    right.set_title("How many defaults the score finds", loc="left", fontsize=11, color=INK)
    pct_axis(right, "x")
    pct_axis(right, "y")
    fig.tight_layout()
    fig.savefig(out / "score_quality.png", dpi=150)
    plt.close(fig)


def credit_policy(cutoffs, challenger, out: Path) -> None:
    """Net benefit by approval rate, and champion vs challenger default rate."""
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.6, 1]})
    data = cutoffs.sort_values("target_approval_rate")
    colors = [BLUE if rec else "#a9c8ef" for rec in data["recommended"]]
    left.bar(data["approval_rate"] * 100, data["net_benefit"] / 1e6, width=3.2, color=colors)
    left.axhline(0, color=INK, lw=0.8)
    best = data[data["recommended"]].iloc[0]
    left.annotate(
        f"recommended: score ≥ {best['minimum_score']:.0f}\n"
        f"approve {best['approval_rate']:.0%}, avoid {best['share_of_defaults_avoided']:.0%} of defaults",
        xy=(best["approval_rate"] * 100, best["net_benefit"] / 1e6),
        xytext=(74, data["net_benefit"].min() / 1e6 * 0.6),
        fontsize=9,
        color=INK,
        arrowprops={"arrowstyle": "-", "color": MUTED},
    )
    left.set_xlabel("Approval rate (%)")
    left.set_ylabel("Net benefit vs approving everybody (millions)")
    left.set_title("Where to set the approval cutoff", loc="left", fontsize=11, color=INK)
    left.grid(axis="x", visible=False)

    data = challenger.sort_values("policy", key=lambda p: ~p.str.startswith("champion"))
    labels = ["Current rules\n(champion)", "Credit score\n(challenger)"]
    rates = data["default_rate_approved"].to_numpy()
    right.bar(labels, rates, color=[GRAY, ORANGE], width=0.5)
    for x, (r, a) in enumerate(zip(rates, data["approval_rate"], strict=True)):
        right.text(x, r + 0.002, f"{r:.2%}\n(approval {a:.0%})", ha="center", fontsize=9, color=INK)
    right.set_ylim(0, rates.max() * 1.35)
    right.set_title("Default rate of approved loans,\nsame approval rate", loc="left", fontsize=11, color=INK)
    pct_axis(right, "y")
    right.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out / "credit_policy.png", dpi=150)
    plt.close(fig)


def main(out: Path) -> None:
    storage = Storage.from_env()
    spark = get_spark(storage)

    def gold(table):
        return read_table(spark, storage, "gold", table).toPandas()

    out.mkdir(parents=True, exist_ok=True)
    performance = gold("model_performance")
    portfolio_rate = performance["defaults"].sum() / performance["customers"].sum()
    risk_drivers(gold("agg_default_by_segment"), portfolio_rate, out)
    score_quality(gold("agg_score_bands").sort_values("score_band"), out)
    credit_policy(gold("policy_cutoff_simulation"), gold("policy_champion_challenger"), out)
    print(f"charts written to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/images"))
    main(parser.parse_args().out)
