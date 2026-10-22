# Local run of the same code that runs as a Databricks job (Spark local mode)
PY ?= python
export PYTHONPATH := src
export CREDIT_RAW_DIR ?= sample_data/raw/home_credit

.PHONY: setup lint test sample-data pipeline powerbi-data charts all wheel clean

setup:
	$(PY) -m pip install -r requirements.txt

lint:
	ruff check .
	ruff format --check src tests scripts ingestion

test:
	$(PY) -m pytest -q

# Regenerate the synthetic sample used by tests and CI (the real data comes from Kaggle)
sample-data:
	$(PY) scripts/make_sample_data.py --out sample_data/raw/home_credit

# bronze -> silver -> gold -> quality gate -> statistics -> scorecard -> policy -> findings
pipeline:
	$(PY) -m credit.pipeline --step all

# README charts from the gold tables
# Gold tables as Parquet files for the Power BI report (DataFolder parameter)
powerbi-data:
	$(PY) scripts/export_powerbi.py --out powerbi/data

charts:
	$(PY) scripts/make_charts.py --out docs/images

all: lint test pipeline

# Package deployed to Databricks by the bundle (databricks.yml)
wheel:
	$(PY) -m pip wheel . --no-deps -w dist

clean:
	rm -rf data reports dist build spark-warehouse src/*.egg-info
