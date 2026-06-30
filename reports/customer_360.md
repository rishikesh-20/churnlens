# Customer360 Profile

Generated from the live warehouse on every Customer360 build — do not edit by hand.

Slice profiled: **`as_of_date = 2011-11-01`** (one row per customer with history strictly before this date, D18).

## Slice summary

- **Customers:** 5,722
- **Active (recency_days ≤ 90, the D3 population):** 2,494 (43.6%)
- **Cancellation-only (no purchase yet, `last_purchase_date` null):** 89
- **Net-negative customers (pure returns to date):** 31
- **Recency days:** median 134, max 700
- **Tenure days:** median 510, max 700
- **Total net product revenue (to date):** £14,954,102.82
- **Total 90-day run rate (revenue-at-risk base, D6):** £2,363,485.88

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
| `distinct_active_months` | int64 | no | `greater_than_or_equal_to(0)` |
| `distinct_active_days` | int64 | no | `greater_than_or_equal_to(0)` |
| `distinct_products` | int64 | no | `greater_than_or_equal_to(0)` |
| `product_line_count` | int64 | no | `greater_than_or_equal_to(0)` |
| `gross_product_revenue` | float64 | no | `greater_than_or_equal_to(0)` |
| `prior_12m_net_revenue` | float64 | no | — |
| `max_invoice_net_revenue` | float64 | no | `greater_than_or_equal_to(0)` |
| `country` | string[python] | no | — |

Frame-level business rules:

- recency_days must not exceed tenure_days
- first_purchase_date must not exceed last_activity_date
- distinct_active_months must not exceed distinct_active_days
- distinct_products must not exceed product_line_count
- max_invoice_net_revenue must not exceed gross_product_revenue
