# Features Profile

Generated from the live warehouse on every feature build — do not edit by hand.

Slice profiled: **`as_of_date = 2011-11-01`** (one model-input row per customer with history strictly before this date, D18/D26).

## Slice summary

- **Customers (rows):** 5,722
- **Features:** 18

Undefined values are NaN, never imputed (D3); coverage below is the non-null share.

| Feature | Non-null | Coverage | Median |
|---------|----------|----------|--------|
| `customer_lifetime_orders` | 5,722 | 100.0% | 3.000 |
| `order_frequency` | 5,722 | 100.0% | 0.245 |
| `purchase_velocity` | 5,722 | 100.0% | 1.000 |
| `purchase_intensity` | 5,722 | 100.0% | 0.009 |
| `average_days_between_orders` | 3,955 | 69.1% | 72.000 |
| `recency_score` | 5,633 | 98.4% | 0.226 |
| `average_order_value` | 5,661 | 98.9% | 272.632 |
| `revenue_per_active_day` | 5,722 | 100.0% | 245.723 |
| `trailing_12m_average_monthly_revenue` | 5,722 | 100.0% | 31.632 |
| `revenue_growth_ratio` | 3,900 | 68.2% | 0.551 |
| `revenue_concentration` | 5,633 | 98.4% | 0.515 |
| `active_months` | 5,722 | 100.0% | 3.000 |
| `product_diversity` | 5,722 | 100.0% | 42.000 |
| `average_products_per_order` | 5,661 | 98.9% | 17.056 |
| `cancellation_rate` | 5,722 | 100.0% | 0.000 |
| `repeat_purchase_ratio` | 5,661 | 98.9% | 0.667 |
| `customer_age_days` | 5,722 | 100.0% | 510.000 |
| `days_since_last_purchase` | 5,633 | 98.4% | 134.000 |

## Features contract (Pandera, enforced on every build)

| Column | Type | Nullable | Checks |
|--------|------|----------|--------|
| `customer_id` | string[python] | no | `str_matches('^\d{5}$')` |
| `as_of_date` | datetime64[ns] | no | — |
| `customer_lifetime_orders` | int64 | no | `greater_than_or_equal_to(0)` |
| `order_frequency` | float64 | yes | `greater_than_or_equal_to(0)` |
| `purchase_velocity` | float64 | yes | `greater_than_or_equal_to(0)` |
| `purchase_intensity` | float64 | yes | `greater_than_or_equal_to(0)`; `less_than_or_equal_to(1)` |
| `average_days_between_orders` | float64 | yes | `greater_than_or_equal_to(0)` |
| `recency_score` | float64 | yes | `greater_than_or_equal_to(0)`; `less_than_or_equal_to(1)` |
| `average_order_value` | float64 | yes | — |
| `revenue_per_active_day` | float64 | no | — |
| `trailing_12m_average_monthly_revenue` | float64 | no | — |
| `revenue_growth_ratio` | float64 | yes | — |
| `revenue_concentration` | float64 | yes | `greater_than_or_equal_to(0)` |
| `active_months` | int64 | no | `greater_than_or_equal_to(0)` |
| `product_diversity` | int64 | no | `greater_than_or_equal_to(0)` |
| `average_products_per_order` | float64 | yes | `greater_than_or_equal_to(0)` |
| `cancellation_rate` | float64 | yes | `greater_than_or_equal_to(0)`; `less_than_or_equal_to(1)` |
| `repeat_purchase_ratio` | float64 | yes | `greater_than_or_equal_to(0)`; `less_than_or_equal_to(1)` |
| `customer_age_days` | int64 | no | `greater_than_or_equal_to(0)` |
| `days_since_last_purchase` | float64 | yes | `greater_than_or_equal_to(0)` |

Frame-level business rules:

- recency_score is null exactly when days_since_last_purchase is
- revenue_concentration must not exceed 1
- order-dependent features are null exactly when there are no orders
