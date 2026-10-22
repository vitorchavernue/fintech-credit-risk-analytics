"""Settings shared by every step: where the data lives and the business assumptions.

All business assumptions (loss given default, margin, score scale) live here, in one
place, so anyone reviewing the analysis can see and change them without reading code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# Source files published by Home Credit (Kaggle "Home Credit Default Risk").
# Only the four files used in the analysis are loaded.
# --------------------------------------------------------------------------------------
SOURCE_FILES: dict[str, str] = {
    "applications": "application_train.csv",  # one row per loan application, with the outcome (defaulted or not)
    "bureau_credits": "bureau.csv",  # loans the customer has at other institutions (credit bureau)
    "previous_applications": "previous_application.csv",  # earlier requests to Home Credit (approved or refused)
    "installment_payments": "installments_payments.csv",  # every installment payment of earlier loans
}

# Code used by the source system when the employment start date is not reported
# (mostly pensioners). It means "about 1,000 years", so it must not be read as a real value.
EMPLOYMENT_NOT_REPORTED = 365243

# --------------------------------------------------------------------------------------
# Business assumptions (can be overridden with environment variables)
# --------------------------------------------------------------------------------------
# Share of the loan amount lost when a customer defaults (after recoveries).
# 45% is the regulatory reference for unsecured loans (Basel foundation approach).
LOSS_GIVEN_DEFAULT = float(os.environ.get("CREDIT_LGD", "0.45"))
# Net profit expected from a loan that is repaid, as a share of the loan amount.
# Used only to compare "money lost to defaults" with "money not earned from good customers rejected".
NET_MARGIN = float(os.environ.get("CREDIT_NET_MARGIN", "0.10"))

# Credit score scale, as used in the market: 600 points means odds of 50 good customers
# for each bad one, and every 20 extra points doubles those odds.
SCORE_BASE_POINTS = 600
SCORE_BASE_ODDS = 50
SCORE_POINTS_TO_DOUBLE_ODDS = 20

# Same random seed everywhere, so every run produces exactly the same numbers.
SEED = 42
# Share of customers kept aside (never seen by the model) to measure it honestly.
TEST_SHARE = 0.30
# Significance level of the statistical tests (5%: accepted chance of a false alarm).
ALPHA = 0.05


@dataclass(frozen=True)
class Storage:
    """Where each layer is stored.

    * Local / CI: folders under ``root`` (``data/bronze/...``), in Delta or Parquet format.
    * Databricks: Unity Catalog tables ``<catalog>.credit_<layer>.<table>`` when ``catalog`` is set.
    """

    root: str = "data"
    raw_dir: str = "data/raw/home_credit"
    table_format: str = "delta"
    catalog: str | None = None
    layers: tuple[str, ...] = field(default=("bronze", "silver", "gold"))

    @classmethod
    def from_env(cls) -> Storage:
        root = os.environ.get("CREDIT_DATA_ROOT", "data")
        return cls(
            root=root,
            raw_dir=os.environ.get("CREDIT_RAW_DIR", f"{root}/raw/home_credit"),
            table_format=os.environ.get("CREDIT_TABLE_FORMAT", "delta"),
            catalog=os.environ.get("CREDIT_CATALOG") or None,
        )

    def table_name(self, layer: str, table: str) -> str:
        """Unity Catalog name of a table (Databricks only)."""
        return f"{self.catalog}.credit_{layer}.{table}"

    def path(self, layer: str, table: str) -> str:
        """Folder of a table (local / CI only)."""
        return f"{self.root.rstrip('/')}/{layer}/{table}"

    def raw_file(self, source: str) -> str:
        """Source file of a table; accepts the plain CSV or its compressed copy (.csv.gz)."""
        return f"{self.raw_dir.rstrip('/')}/{SOURCE_FILES[source]}*"
