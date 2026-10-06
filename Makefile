SHELL := /bin/bash
export PYTHONPATH := $(CURDIR)/src
export DUCKDB_PATH ?= $(CURDIR)/data/warehouse.duckdb
export LAKE_PATH ?= $(CURDIR)/data/lake
export RAW_PATH ?= $(CURDIR)/data/raw
export DBT_PROFILES_DIR := $(CURDIR)/dbt_project
PY ?= python
DAYS ?= 92

.DEFAULT_GOAL := help
.PHONY: help setup data spark dbt train report demo test lint docs clean up down

help:  ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

setup:  ## Install Python dependencies
	pip install -r requirements.txt -r requirements-dev.txt

data:  ## Generate synthetic raw CSV files (DAYS=92 by default)
	$(PY) -m payments.generate_data --days $(DAYS)

spark:  ## Spark: clean raw CSVs -> partitioned Parquet lake
	$(PY) -m payments.spark_clean --all

dbt:  ## dbt: seed + build models + run tests (DuckDB)
	cd dbt_project && dbt build

train:  ## Train fraud model, write scores back to the warehouse
	$(PY) -m payments.train_fraud_model

report:  ## Build charts (docs/images) and CSV exports of the marts
	$(PY) -m payments.report

demo: data spark dbt train report  ## Run the whole pipeline end to end, no credentials needed

test:  ## Unit tests (data generator + Spark cleaning logic)
	pytest -q

lint:  ## Lint the Python code
	ruff check src tests dags

docs:  ## Build dbt docs (lineage graph) and serve them
	cd dbt_project && dbt docs generate && dbt docs serve

clean:  ## Delete generated data, models and reports
	rm -rf data models exports reports/*.json reports/*.csv dbt_project/target dbt_project/logs

up:  ## Start Airflow at http://localhost:8080
	docker compose up --build

down:  ## Stop Airflow
	docker compose down
