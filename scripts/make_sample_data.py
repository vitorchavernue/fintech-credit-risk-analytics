"""Creates a small SYNTHETIC sample with the same layout as the Home Credit files.

Why it exists: the real Home Credit data cannot be redistributed (Kaggle competition
rules), but the automated tests and the CI need data to run the whole pipeline.
This script generates fake customers that behave like real ones (riskier customers
pay late more often, have more refused applications and default more), using the
exact file and column names of the original dataset.

Nothing here is real data. The real analysis runs on the files downloaded from Kaggle.

Usage:
    python scripts/make_sample_data.py --out sample_data/raw/home_credit --customers 6000
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

# Category values exactly as they appear in the original files
CONTRACT_TYPES = ["Cash loans", "Revolving loans"]
INCOME_TYPES = ["Working", "Commercial associate", "Pensioner", "State servant", "Unemployed"]
EDUCATION = [
    "Secondary / secondary special",
    "Higher education",
    "Incomplete higher",
    "Lower secondary",
    "Academic degree",
]
FAMILY = ["Married", "Single / not married", "Civil marriage", "Separated", "Widow"]
HOUSING = ["House / apartment", "With parents", "Municipal apartment", "Rented apartment", "Office apartment"]
OCCUPATIONS = ["Laborers", "Sales staff", "Core staff", "Managers", "Drivers", "High skill tech staff", "Accountants"]
ORGANIZATIONS = ["Business Entity Type 3", "Self-employed", "Government", "Medicine", "Trade: type 7", "School", "XNA"]
BUREAU_TYPES = ["Consumer credit", "Credit card", "Car loan", "Mortgage", "Microloan"]
PREV_TYPES = ["Cash loans", "Consumer loans", "Revolving loans"]
REJECT_REASONS = ["HC", "LIMIT", "SCO", "SCOFR", "VERIF"]
EMPLOYMENT_PLACEHOLDER = 365243  # the code the source system uses when employment is not reported


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def fmt(value) -> str:
    """Writes empty text for missing values, as the original CSV files do."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value)


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows([[fmt(v) for v in row] for row in rows])


def main(out: Path, customers: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Each fake customer gets a hidden "risk level". Everything else
    #    (external scores, late payments, default) is derived from it, so
    #    the sample keeps the same cause-and-effect as the real portfolio.
    # ------------------------------------------------------------------
    ids = np.arange(100002, 100002 + customers)
    risk = rng.normal(0, 1, customers)
    defaulted = rng.random(customers) < sigmoid(-2.7 + 1.1 * risk)  # about 8% default, like the real data

    income_type = rng.choice(INCOME_TYPES, customers, p=[0.52, 0.23, 0.18, 0.068, 0.002])
    age_days = -(rng.integers(21, 69, customers) * 365.25).astype(int)
    employed_days = -(rng.gamma(2.0, 900, customers)).astype(int)
    # Pensioners and unemployed people have no employment date in the source system
    employed_days = np.where(np.isin(income_type, ["Pensioner", "Unemployed"]), EMPLOYMENT_PLACEHOLDER, employed_days)

    income = np.round(rng.lognormal(11.9, 0.5, customers), -2)
    credit = np.round(income * rng.uniform(0.8, 5.0, customers), -2)
    annuity = np.round(credit * rng.uniform(0.04, 0.09, customers) * (1 + 0.15 * np.clip(risk, 0, None)), 1)
    goods = np.where(rng.random(customers) < 0.98, np.round(credit * rng.uniform(0.8, 1.0, customers), -2), np.nan)

    def external_score(noise: float, missing_share: float) -> np.ndarray:
        """External bureau scores: higher means safer; some are missing, as in the real file."""
        score = np.round(sigmoid(-0.9 * risk + rng.normal(0, noise, customers)), 6)
        return np.where(rng.random(customers) < missing_share, np.nan, score)

    ext1, ext2, ext3 = external_score(1.0, 0.56), external_score(0.8, 0.002), external_score(0.9, 0.20)
    gender = rng.choice(["F", "M"], customers, p=[0.66, 0.34]).astype(object)
    gender[rng.choice(customers, 2, replace=False)] = "XNA"  # a few unknown codes, as in the real file
    occupation = rng.choice(OCCUPATIONS, customers).astype(object)
    occupation[rng.random(customers) < 0.31] = None

    applications = [
        [
            ids[i],
            int(defaulted[i]),
            rng.choice(CONTRACT_TYPES, p=[0.9, 0.1]),
            gender[i],
            rng.choice(["Y", "N"], p=[0.34, 0.66]),
            rng.choice(["Y", "N"], p=[0.69, 0.31]),
            int(rng.poisson(0.4)),
            income[i],
            credit[i],
            annuity[i],
            goods[i],
            income_type[i],
            rng.choice(EDUCATION, p=[0.71, 0.24, 0.033, 0.012, 0.005]),
            rng.choice(FAMILY, p=[0.64, 0.15, 0.1, 0.06, 0.05]),
            rng.choice(HOUSING, p=[0.89, 0.05, 0.03, 0.02, 0.01]),
            age_days[i],
            employed_days[i],
            occupation[i],
            float(rng.integers(1, 5)),
            int(np.clip(2 + np.round(risk[i] * 0.6 + rng.normal(0, 0.5)), 1, 3)),
            rng.choice(ORGANIZATIONS),
            ext1[i],
            ext2[i],
            ext3[i],
        ]
        for i in range(customers)
    ]
    write_csv(
        out / "application_train.csv",
        [
            "SK_ID_CURR", "TARGET", "NAME_CONTRACT_TYPE", "CODE_GENDER", "FLAG_OWN_CAR", "FLAG_OWN_REALTY",
            "CNT_CHILDREN", "AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "AMT_GOODS_PRICE",
            "NAME_INCOME_TYPE", "NAME_EDUCATION_TYPE", "NAME_FAMILY_STATUS", "NAME_HOUSING_TYPE",
            "DAYS_BIRTH", "DAYS_EMPLOYED", "OCCUPATION_TYPE", "CNT_FAM_MEMBERS", "REGION_RATING_CLIENT_W_CITY",
            "ORGANIZATION_TYPE", "EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3",
        ],
        applications,
    )  # fmt: skip

    # ------------------------------------------------------------------
    # 2. Credit bureau: loans the customer has at OTHER institutions.
    #    Riskier customers have more overdue and bad-debt records.
    #    A few records belong to customers outside this file, as happens in
    #    the real data (they belong to the Kaggle test set).
    # ------------------------------------------------------------------
    bureau, bureau_id = [], 5000000
    owners = list(ids) + list(range(900000, 900000 + customers // 50))
    for owner in owners:
        r = risk[owner - 100002] if owner < 900000 else 0.0
        for _ in range(rng.poisson(4)):
            bureau_id += 1
            status = rng.choice(["Closed", "Active", "Sold", "Bad debt"], p=[0.62, 0.37, 0.009, 0.001])
            overdue_days = int(rng.integers(1, 120)) if rng.random() < sigmoid(-4.0 + 1.2 * r) else 0
            amount = round(float(rng.lognormal(11.5, 1.0)), 1)
            debt = round(amount * rng.uniform(0, 0.9), 1) if status == "Active" else 0.0
            bureau.append(
                [
                    owner, bureau_id, status, rng.choice(["currency 1", "currency 2"], p=[0.999, 0.001]),
                    -int(rng.integers(30, 2900)), overdue_days, round(amount * 0.05, 1) if overdue_days else "",
                    int(rng.poisson(0.01)), amount, debt, round(amount * 0.02, 1) if overdue_days else 0.0,
                    rng.choice(BUREAU_TYPES, p=[0.73, 0.23, 0.02, 0.015, 0.005]),
                ]
            )  # fmt: skip
    write_csv(
        out / "bureau.csv",
        [
            "SK_ID_CURR", "SK_ID_BUREAU", "CREDIT_ACTIVE", "CREDIT_CURRENCY", "DAYS_CREDIT", "CREDIT_DAY_OVERDUE",
            "AMT_CREDIT_MAX_OVERDUE", "CNT_CREDIT_PROLONG", "AMT_CREDIT_SUM", "AMT_CREDIT_SUM_DEBT",
            "AMT_CREDIT_SUM_OVERDUE", "CREDIT_TYPE",
        ],
        bureau,
    )  # fmt: skip

    # ------------------------------------------------------------------
    # 3. Previous applications at Home Credit and 4. their installments.
    #    Riskier customers are refused more often and pay installments late.
    # ------------------------------------------------------------------
    previous, installments, prev_id = [], [], 1000000
    for i, owner in enumerate(ids):
        for _ in range(rng.poisson(3)):
            prev_id += 1
            refused = rng.random() < sigmoid(-1.6 + 0.8 * risk[i])
            status = "Refused" if refused else rng.choice(["Approved", "Canceled", "Unused offer"], p=[0.8, 0.17, 0.03])
            amount = round(float(rng.lognormal(11.3, 0.8)), 1)
            previous.append(
                [
                    prev_id, owner, rng.choice(PREV_TYPES, p=[0.45, 0.45, 0.10]), amount,
                    amount if status == "Approved" else 0.0, status, -int(rng.integers(10, 2900)),
                    rng.choice(REJECT_REASONS) if refused else "XAP", "Y" if rng.random() < 0.995 else "N",
                    1 if rng.random() < 0.996 else 0,
                ]
            )  # fmt: skip
            if status != "Approved":
                continue
            instalment = round(amount / 12, 3)
            start = -int(rng.integers(400, 2800))
            for number in range(1, int(rng.integers(6, 13)) + 1):
                due = start + 30 * number
                late = int(rng.integers(1, 45)) if rng.random() < sigmoid(-2.6 + 1.0 * risk[i]) else 0
                if rng.random() < 0.002:  # installment never paid: no payment date in the file
                    installments.append([prev_id, owner, 1.0, number, float(due), "", instalment, ""])
                elif rng.random() < 0.05:  # paid in two parts on different days
                    first = round(instalment * 0.6, 3)
                    installments.append([prev_id, owner, 1.0, number, float(due), float(due - 3), instalment, first])
                    installments.append(
                        [
                            prev_id,
                            owner,
                            1.0,
                            number,
                            float(due),
                            float(due + late),
                            instalment,
                            round(instalment - first, 3),
                        ]
                    )
                else:
                    paid = round(instalment * (0.5 if rng.random() < 0.01 else 1.0), 3)
                    installments.append(
                        [prev_id, owner, 1.0, number, float(due), float(due + late - 2), instalment, paid]
                    )
    write_csv(
        out / "previous_application.csv",
        [
            "SK_ID_PREV", "SK_ID_CURR", "NAME_CONTRACT_TYPE", "AMT_APPLICATION", "AMT_CREDIT",
            "NAME_CONTRACT_STATUS", "DAYS_DECISION", "CODE_REJECT_REASON", "FLAG_LAST_APPL_PER_CONTRACT",
            "NFLAG_LAST_APPL_IN_DAY",
        ],
        previous,
    )  # fmt: skip
    write_csv(
        out / "installments_payments.csv",
        [
            "SK_ID_PREV", "SK_ID_CURR", "NUM_INSTALMENT_VERSION", "NUM_INSTALMENT_NUMBER", "DAYS_INSTALMENT",
            "DAYS_ENTRY_PAYMENT", "AMT_INSTALMENT", "AMT_PAYMENT",
        ],
        installments,
    )  # fmt: skip
    print(
        f"{customers} applications, {len(bureau)} bureau credits, {len(previous)} previous applications, "
        f"{len(installments)} installment payments -> {out}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("sample_data/raw/home_credit"))
    parser.add_argument("--customers", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.out, args.customers, args.seed)
