# ChurnLens

[![CI](https://github.com/rishikesh-20/churnlens/actions/workflows/ci.yml/badge.svg)](https://github.com/rishikesh-20/churnlens/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

ML platform for customer churn prediction on the Online Retail II dataset: 90-day churn
probabilities, revenue-at-risk, SHAP explanations, daily Airflow scoring, drift
monitoring with gated retraining, Slack alerting, and a React operations dashboard.

> Under active development — this README documents what is implemented so far and grows
> as the project does.

## Implemented so far

- **Foundation** — uv-managed Python 3.11 project (src layout), typed pydantic-settings
  configuration, centralized logging, and the platform's core temporal contract: every
  pipeline component takes an explicit `as_of_date` cutoff and may only read data from
  strictly before it, making point-in-time correctness testable and every pipeline run
  idempotently reproducible.
- **Ingestion** — bronze layer of a medallion warehouse on DuckDB (one file, one SQL
  schema per layer). Online Retail II loads as an exact, immutable copy of the source —
  no cleaning or filtering, snake_case names and lineage columns (`source_file`,
  `source_sheet`, `loaded_at`) only. The load is a full atomic replace, so ingestion is
  idempotent and bronze is always reloadable from source. Each run also exports the
  table to Parquet and regenerates a profiled
  [data dictionary](reports/data_dictionary.md) from the live warehouse.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.11 pinned via `.python-version`).

```sh
git clone https://github.com/rishikesh-20/churnlens
cd churnlens
uv sync
cp .env.example .env          # optional local overrides
uv run pre-commit install     # enable git hooks
```

## Data

The dataset is [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
(UCI ML Repository): ~1M invoice lines from a UK online retailer, Dec 2009 – Dec 2011.
It is not committed to the repo — download the zip from UCI and place the extracted
workbook at `data/raw/online_retail_II.xlsx`, then:

```sh
uv run python scripts/ingest.py
```

This builds `bronze.transactions` in `data/warehouse.duckdb`, exports
`data/bronze/transactions.parquet`, and regenerates `reports/data_dictionary.md`.

## Development

```sh
uv run pytest                 # tests with coverage
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy src/              # type check
```

## Layout

```
data/raw/                    source dataset (manual download, gitignored)
data/warehouse.duckdb        DuckDB warehouse: bronze/silver/gold schemas (gitignored)
data/{bronze,silver,gold}/   per-layer Parquet exports (contents gitignored)
airflow/                     orchestration
frontend/                    operations dashboard
reports/                     generated reports
tests/                       pytest suite
scripts/                     operational entrypoints
src/churnlens/               Python package
```
