# Labels Profile

Generated from the live warehouse on every label build — do not edit by hand.

Most recently built slice: **`snapshot_date = 2011-11-01`**. The target is *no product purchase* in `[snapshot, snapshot + 90d)`, over the D3 active population (`recency_days ≤ 90`, read from `gold.customer_360`).

## Snapshots in `gold.labels`

Active churn rate excludes censored rows (immature window, outcome unknowable).

| snapshot_date | customers | churned | retained | censored | active churn rate |
|---------------|-----------|---------|----------|----------|-------------------|
| 2010-03-01 | 1,802 | 711 | 1,091 | 0 | 39.5% |
| 2010-04-01 | 1,866 | 766 | 1,100 | 0 | 41.1% |
| 2010-05-01 | 2,001 | 866 | 1,135 | 0 | 43.3% |
| 2010-06-01 | 2,080 | 938 | 1,142 | 0 | 45.1% |
| 2010-07-01 | 2,091 | 911 | 1,180 | 0 | 43.6% |
| 2010-08-01 | 2,076 | 756 | 1,320 | 0 | 36.4% |
| 2010-09-01 | 1,985 | 634 | 1,351 | 0 | 31.9% |
| 2010-10-01 | 2,079 | 777 | 1,302 | 0 | 37.4% |
| 2010-11-01 | 2,546 | 1,195 | 1,351 | 0 | 46.9% |
| 2010-12-01 | 2,917 | 1,698 | 1,219 | 0 | 58.2% |
| 2011-01-01 | 2,710 | 1,579 | 1,131 | 0 | 58.3% |
| 2011-02-01 | 2,247 | 1,201 | 1,046 | 0 | 53.4% |
| 2011-03-01 | 1,749 | 775 | 974 | 0 | 44.3% |
| 2011-04-01 | 1,812 | 767 | 1,045 | 0 | 42.3% |
| 2011-05-01 | 1,925 | 791 | 1,134 | 0 | 41.1% |
| 2011-06-01 | 1,993 | 879 | 1,114 | 0 | 44.1% |
| 2011-07-01 | 2,001 | 821 | 1,180 | 0 | 41.0% |
| 2011-08-01 | 2,060 | 764 | 1,296 | 0 | 37.1% |
| 2011-09-01 | 1,958 | 633 | 1,325 | 0 | 32.3% |
| 2011-10-01 | 2,189 | 0 | 1,368 | 821 | 0.0% |
| 2011-11-01 | 2,494 | 0 | 1,206 | 1,288 | 0.0% |

## Labels contract (Pandera, enforced on every build)

| Column | Type | Nullable | Checks |
|--------|------|----------|--------|
| `customer_id` | string[python] | no | `str_matches('^\d{5}$')` |
| `snapshot_date` | datetime64[ns] | no | — |
| `churned` | Int64 | yes | `isin([0, 1])` |
| `censored` | bool | no | — |
| `next_purchase_date` | datetime64[ns] | yes | — |

Frame-level business rules:

- churned is null exactly when censored
- next_purchase_date is set exactly when churned == 0
- next_purchase_date must not precede snapshot_date
