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
- **Validation** — silver layer built from bronze under runtime data contracts
  ([Pandera](https://pandera.readthedocs.io/)). Cleaning rules remove only *known* dirt
  and account for every dropped row — the workbook's inter-sheet export overlap is
  deduplicated and anonymous rows are dropped; cancellations stay as negative line items
  and service codes (postage, fees, adjustments) are flagged out of revenue rather than
  deleted. A strict contract (types, nulls, value ranges, and business rules like
  `line_revenue = quantity × unit_price` and cancellation/quantity consistency) then
  validates the entire candidate table; any surprise violation aborts the build before
  anything is written. Every run regenerates a
  [data quality report](reports/data_quality.md) with the row-loss waterfall, excluded
  codes, and the enforced contract.
- **Customer360** — gold-layer customer analytics mart, the first layer above the
  simulated clock. For a given `as_of_date` it aggregates silver history *strictly before*
  the cutoff into one row per customer: recency and tenure, order and return counts,
  net-product revenue, a 90-day revenue run rate, and country — every metric anchored on
  the passed date, never the latest data, so the table cannot read the future. The build
  is an idempotent per-slice upsert, so replaying snapshots accumulates a
  `(customer, as_of_date)` panel that later phases label and turn into features; a strict
  Pandera contract validates each slice before it is written, and every run regenerates a
  [Customer360 profile](reports/customer_360.md). Anti-leakage is asserted by tests (a row
  timestamped at the exact cutoff is excluded; post-cutoff rows never change a metric).
- **Labeling** — the supervised churn target (`gold.labels`), one row per customer per
  monthly snapshot over the active population (recency ≤ 90 days, read from Customer360).
  A customer is labelled *churned* if they make no product purchase in the 90 days *after*
  the snapshot — the platform's one deliberate look-ahead, used for the target only and
  cleanly partitioned from features, which stay strictly before the snapshot. Snapshots
  whose 90-day window runs past the end of observed data are *censored* (event-aware: a
  purchase already seen settles the outcome; otherwise it is unknowable and held out of
  training). The build is an idempotent per-snapshot upsert, so a rolling monthly schedule
  accumulates a reusable training panel that also drives replay and retraining; a strict
  Pandera contract validates each slice and every run regenerates a
  [labels profile](reports/labels.md). Anti-leakage is asserted by tests (injecting a
  post-snapshot purchase flips the label but changes no feature; window boundaries are
  half-open).

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

```sh
uv run python scripts/build_silver.py
```

This validates bronze, builds `silver.transactions` (cleaned, deduplicated, contract-
enforced), exports `data/silver/transactions.parquet`, and regenerates
`reports/data_quality.md` and the data dictionary.

```sh
uv run python scripts/build_customer360.py 2011-03-01
```

This builds the `gold.customer_360` slice for the given cutoff date (one row per customer,
point-in-time), upserts it into the panel, exports `data/gold/customer_360.parquet`, and
regenerates `reports/customer_360.md` and the data dictionary.

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
