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

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.11 pinned via `.python-version`).

```sh
git clone https://github.com/rishikesh-20/churnlens
cd churnlens
uv sync
cp .env.example .env          # optional local overrides
uv run pre-commit install     # enable git hooks
```

## Development

```sh
uv run pytest                 # tests with coverage
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy src/              # type check
```

## Layout

```
data/{bronze,silver,gold}/   medallion data layers (contents gitignored)
airflow/                     orchestration
frontend/                    operations dashboard
reports/                     generated reports
tests/                       pytest suite
scripts/                     operational entrypoints
src/churnlens/               Python package
```
