# Customer360 Profile

Generated from the live warehouse on every Customer360 build — do not edit by hand.

Slice profiled: **`as_of_date = 2011-03-01`** (one row per customer with history strictly before this date, D18).

## Slice summary

- **Customers:** 4,607
- **Active (recency_days ≤ 90, the D3 population):** 1,749 (38.0%)
- **Cancellation-only (no purchase yet, `last_purchase_date` null):** 95
- **Net-negative customers (pure returns to date):** 34
- **Recency days:** median 110, max 455
- **Tenure days:** median 327, max 455
- **Total net product revenue (to date):** £9,583,181.41
- **Total 90-day run rate (revenue-at-risk base, D6):** £2,469,858.07

## Customer360 contract (Pandera, enforced on every build)

| Column | Type | Nullable | Checks |
|--------|------|----------|--------|
| `customer_id` | string[python] | no | `str_matches('^\d{5}$')` |
| `as_of_date` | datetime64[ns] | no | — |
| `first_purchase_date` | datetime64[ns] | no | — |
| `last_activity_date` | datetime64[ns] | no | — |
| `last_purchase_date` | datetime64[ns] | yes | — |
| `recency_days` | int64 | no | `greater_than_or_equal_to(0)` |
| `tenure_days` | int64 | no | `greater_than_or_equal_to(0)` |
| `order_count` | int64 | no | `greater_than_or_equal_to(0)` |
| `cancelled_order_count` | int64 | no | `greater_than_or_equal_to(0)` |
| `total_net_revenue` | float64 | no | — |
| `trailing_12m_net_revenue` | float64 | no | — |
| `cancelled_revenue` | float64 | no | `less_than_or_equal_to(0)` |
| `run_rate_90d` | float64 | no | — |
| `country` | string[python] | no | — |

Frame-level business rules:

- recency_days must not exceed tenure_days
- first_purchase_date must not exceed last_activity_date
