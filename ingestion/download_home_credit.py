"""Brings the Home Credit files into the raw area of the lake.

Two ways to get the data (both need a Kaggle account that accepted the competition rules
at kaggle.com/competitions/home-credit-default-risk):
* automatic: ``--from-kaggle`` downloads it with the Kaggle API (kagglehub);
* manual: download the zip from the Kaggle page and pass it with ``--zip``.

Only the four files used by the analysis are copied, compressed (.csv.gz), so the raw
area takes about 0.5 GB instead of 2.5 GB. Spark reads compressed files directly.

Usage:
    python ingestion/download_home_credit.py --from-kaggle --target data/raw/home_credit
    python ingestion/download_home_credit.py --zip ~/Downloads/home-credit-default-risk.zip
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit.config import SOURCE_FILES  # noqa: E402

COMPETITION = "home-credit-default-risk"


def compress(source, target: Path) -> None:
    """Copies one CSV into the raw area as .csv.gz (streamed: never loads it all in memory)."""
    with gzip.open(target, "wb", compresslevel=6) as out:
        shutil.copyfileobj(source, out, length=16 * 1024 * 1024)


def from_zip(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for name in SOURCE_FILES.values():
            with archive.open(name) as source:
                compress(source, target / f"{name}.gz")
            print(f"  {name} -> {target / (name + '.gz')}")


def from_kaggle(target: Path) -> None:
    import kagglehub  # needs Kaggle credentials (~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY)

    folder = Path(kagglehub.competition_download(COMPETITION))
    for name in SOURCE_FILES.values():
        with (folder / name).open("rb") as source:
            compress(source, target / f"{name}.gz")
        print(f"  {name} -> {target / (name + '.gz')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-kaggle", action="store_true", help="download with the Kaggle API")
    source.add_argument("--zip", type=Path, help="zip downloaded manually from Kaggle")
    parser.add_argument("--target", type=Path, default=Path("data/raw/home_credit"))
    args = parser.parse_args()

    args.target.mkdir(parents=True, exist_ok=True)
    if args.from_kaggle:
        from_kaggle(args.target)
    else:
        from_zip(args.zip, args.target)
