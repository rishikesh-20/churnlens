# Data Dictionary

Generated from the live warehouse on every pipeline run — do not edit by hand.

## `bronze.transactions`

Raw Online Retail II invoice lines, exactly as in the source workbook ([UCI 502](https://archive.ics.uci.edu/dataset/502/online+retail+ii)). One row per invoice line; no cleaning or filtering.

**Rows:** 1,067,371

| Column | Type | Nulls | Distinct | Min | Max | Description |
|--------|------|-------|----------|-----|-----|-------------|
| `invoice` | VARCHAR | 0 | 53,628 | 489434 | C581569 | Invoice number (text); prefixed 'C' for cancellations. |
| `stock_code` | VARCHAR | 0 | 5,305 | 10002 | m | Product (item) code. |
| `description` | VARCHAR | 4,382 | 5,698 |   DOORMAT UNION JACK GUNS AND ROSES | wrongly sold sets | Product name; null on some non-product rows. |
| `quantity` | BIGINT | 0 | 1,057 | -80995 | 80995 | Units on the invoice line; negative for cancellations. |
| `invoice_date` | TIMESTAMP | 0 | 47,635 | 2009-12-01 07:45:00 | 2011-12-09 12:50:00 | Invoice timestamp. |
| `unit_price` | DOUBLE | 0 | 2,807 | -53594.36 | 38970.0 | Price per unit in GBP. |
| `customer_id` | VARCHAR | 243,007 | 5,942 | 12346 | 18287 | Customer identifier; null for unregistered (anonymous) sales. |
| `country` | VARCHAR | 0 | 43 | Australia | West Indies | Customer's country of residence. |
| `source_file` | VARCHAR | 0 | 1 | online_retail_II.xlsx | online_retail_II.xlsx | Lineage: source workbook file name. |
| `source_sheet` | VARCHAR | 0 | 2 | Year 2009-2010 | Year 2010-2011 | Lineage: workbook sheet the row was read from. |
| `loaded_at` | TIMESTAMP | 0 | 1 | 2026-06-12 03:07:23.101187 | 2026-06-12 03:07:23.101187 | Lineage: UTC timestamp of the bronze load run. |

## `silver.transactions`

Cleaned invoice lines: inter-sheet duplicate copies and anonymous rows removed, derived revenue and flags added. A strict Pandera contract validates every build before the table is written; row losses are accounted in [data_quality.md](data_quality.md).

**Rows:** 809,561

| Column | Type | Nulls | Distinct | Min | Max | Description |
|--------|------|-------|----------|-----|-----|-------------|
| `invoice` | VARCHAR | 0 | 44,876 | 489434 | C581569 | Invoice number (text); prefixed 'C' for cancellations. |
| `stock_code` | VARCHAR | 0 | 4,646 | 10002 | TEST002 | Product (item) code. |
| `description` | VARCHAR | 0 | 5,299 |   DOORMAT UNION JACK GUNS AND ROSES | ZINC WIRE SWEETHEART LETTER TRAY | Product name. |
| `quantity` | BIGINT | 0 | 643 | -80995 | 80995 | Units on the invoice line; negative for cancellations. |
| `invoice_date` | TIMESTAMP | 0 | 41,439 | 2009-12-01 07:45:00 | 2011-12-09 12:50:00 | Invoice timestamp. |
| `unit_price` | DOUBLE | 0 | 1,022 | 0.0 | 38970.0 | Price per unit in GBP. |
| `customer_id` | VARCHAR | 0 | 5,942 | 12346 | 18287 | Customer identifier; never null in silver. |
| `country` | VARCHAR | 0 | 41 | Australia | West Indies | Customer's country of residence. |
| `line_revenue` | DOUBLE | 0 | 5,625 | -168469.6 | 168469.6 | quantity * unit_price in GBP; negative for cancellations. |
| `is_cancellation` | BOOLEAN | 0 | 2 | false | true | True when the invoice is a cancellation ('C' prefix). |
| `is_product` | BOOLEAN | 0 | 2 | false | true | True for merchandise stock codes; False for service/adjustment codes (postage, fees, manual adjustments) excluded from revenue. |
| `source_file` | VARCHAR | 0 | 1 | online_retail_II.xlsx | online_retail_II.xlsx | Lineage: source workbook file name. |
| `source_sheet` | VARCHAR | 0 | 2 | Year 2009-2010 | Year 2010-2011 | Lineage: workbook sheet the row was read from. |
| `loaded_at` | TIMESTAMP | 0 | 1 | 2026-06-12 03:07:23.101187 | 2026-06-12 03:07:23.101187 | Lineage: UTC timestamp of the bronze load run. |

## `gold.customer_360`

Point-in-time customer analytics mart: one row per customer per `as_of_date`, aggregated from silver history strictly before the cutoff (D18). Durable facts only (recency/tenure, order and return counts, net-product revenue, the D6 run rate, most-recent country); a single-date slice is profiled in [customer_360.md](customer_360.md).

**Rows:** 86,045

| Column | Type | Nulls | Distinct | Min | Max | Description |
|--------|------|-------|----------|-----|-----|-------------|
| `customer_id` | VARCHAR | 0 | 5,722 | 12346 | 18287 | Customer identifier. |
| `as_of_date` | DATE | 0 | 21 | 2010-03-01 | 2011-11-01 | Point-in-time cutoff; metrics use only history strictly before it (D18). |
| `first_purchase_date` | DATE | 0 | 561 | 2009-12-01 | 2011-10-31 | Date of the customer's first line (tenure anchor). |
| `last_activity_date` | DATE | 0 | 570 | 2009-12-01 | 2011-10-31 | Date of the most recent line of any kind; cancellations count as activity (D11). Drives recency. |
| `last_purchase_date` | DATE | 2,015 | 570 | 2009-12-01 | 2011-10-31 | Date of the most recent product purchase (positive quantity); null if the customer has only cancellations so far. |
| `recency_days` | INTEGER | 0 | 687 | 1 | 700 | as_of_date minus last_activity_date, in days. |
| `tenure_days` | INTEGER | 0 | 689 | 1 | 700 | as_of_date minus first_purchase_date, in days. |
| `order_count` | INTEGER | 0 | 184 | 0 | 355 | Distinct non-cancellation invoices. |
| `cancelled_order_count` | INTEGER | 0 | 74 | 0 | 105 | Distinct cancellation ('C') invoices. |
| `total_net_revenue` | DOUBLE | 0 | 30,534 | -1663.0600000000002 | 551592.0200000001 | Net product revenue to date in GBP (cancellations net out; non-product codes excluded, D11). May be negative. |
| `trailing_12m_net_revenue` | DOUBLE | 0 | 34,224 | -9854.030000000002 | 318751.33999999997 | Net product revenue in the trailing 12 months before the cutoff, feeding the D6 run rate. |
| `cancelled_revenue` | DOUBLE | 0 | 4,797 | -77621.14000000001 | 0.0 | Net revenue of cancellation lines in GBP (≤ 0). |
| `run_rate_90d` | DOUBLE | 0 | 63,113 | -2429.7608219178087 | 102284.44 | Expected 90-day net revenue (D6): trailing-12m scaled by 90/365, or a full-history rate floored at the churn window for <12mo customers. |
| `distinct_active_months` | INTEGER | 0 | 23 | 1 | 23 | Count of distinct calendar months with any activity before the cutoff (D25). |
| `distinct_active_days` | INTEGER | 0 | 163 | 1 | 258 | Count of distinct calendar days with any activity before the cutoff (D25). |
| `distinct_products` | INTEGER | 0 | 727 | 0 | 2425 | Count of distinct product stock codes actually purchased (positive product lines) before the cutoff (D25). |
| `product_line_count` | INTEGER | 0 | 1,277 | 0 | 10827 | Count of positive product invoice lines before the cutoff (D25). |
| `gross_product_revenue` | DOUBLE | 0 | 29,096 | 0.0 | 554170.4200000002 | Total revenue of positive product lines before the cutoff (returns not netted); the denominator for revenue concentration (D25). |
| `prior_12m_net_revenue` | DOUBLE | 0 | 12,920 | -1663.0600000000002 | 296658.83 | Net product revenue in the window 24-12 months before the cutoff, i.e. the year before trailing_12m_net_revenue; feeds revenue growth (D25). |
| `max_invoice_net_revenue` | DOUBLE | 0 | 9,538 | 0.0 | 77183.6 | Largest single non-cancellation invoice's net product revenue before the cutoff; 0 if the customer has no order. Feeds revenue concentration (D25). |
| `country` | VARCHAR | 0 | 41 | Australia | West Indies | Country on the customer's most recent invoice before the cutoff. |

## `gold.features`

Model-ready feature vector: one row per customer per `as_of_date`, each feature a closed-form per-row transform of the `gold.customer_360` slice (D26). No cross-customer statistics and no forward read, so the same builder serves training and scoring with no skew. Undefined values are NaN, never imputed (D3). Profiled in [features.md](features.md).

**Rows:** 86,045

| Column | Type | Nulls | Distinct | Min | Max | Description |
|--------|------|-------|----------|-----|-----|-------------|
| `customer_id` | VARCHAR | 0 | 5,722 | 12346 | 18287 | Customer identifier. |
| `as_of_date` | DATE | 0 | 21 | 2010-03-01 | 2011-11-01 | Point-in-time cutoff; features use only customer_360 facts as of this date (D18). |
| `customer_lifetime_orders` | INTEGER | 0 | 184 | 0 | 355 | Total distinct non-cancellation invoices to date. |
| `order_frequency` | DOUBLE | 0 | 7,525 | 0.0 | 120.0 | Orders per 30 calendar days of tenure; NaN if tenure is 0 days. |
| `purchase_velocity` | DOUBLE | 0 | 689 | 0.0 | 22.0 | Orders per distinct active month — order cadence while engaged. |
| `purchase_intensity` | DOUBLE | 0 | 7,361 | 0.0014285714285714286 | 1.0 | Share of tenure days on which the customer was active, in (0,1]. |
| `average_days_between_orders` | DOUBLE | 31,223 | 5,455 | 0.0 | 687.0 | Mean gap between first and last purchase across orders; NaN for customers with fewer than two orders. |
| `recency_score` | DOUBLE | 2,015 | 686 | 0.0004189421234483841 | 0.9889503892939223 | exp(-days_since_last_purchase / 90): 1 just after a purchase, decaying to ~0.37 at one churn window; NaN if the customer has never purchased. |
| `average_order_value` | DOUBLE | 1,467 | 30,005 | -831.5300000000001 | 13280.46 | Net revenue per order; NaN if no orders. May be negative (net of returns). |
| `revenue_per_active_day` | DOUBLE | 0 | 30,131 | -831.5300000000001 | 39619.5 | Net revenue per distinct active day. |
| `trailing_12m_average_monthly_revenue` | DOUBLE | 0 | 33,517 | -821.1691666666669 | 26562.611666666664 | Trailing-12-month net revenue divided by 12. |
| `revenue_growth_ratio` | DOUBLE | 58,131 | 14,464 | -1.0000000000000002 | 6.2263672223280664e+16 | Trailing-12m net revenue over prior-12m net revenue; NaN when the prior year's revenue is not positive. |
| `revenue_concentration` | DOUBLE | 2,015 | 24,430 | 0.01533468870480068 | 1.0000000000000007 | Largest order's share of gross product revenue, in (0,1]; NaN when the customer has no positive product revenue. |
| `active_months` | INTEGER | 0 | 23 | 1 | 23 | Count of distinct calendar months with activity. |
| `product_diversity` | INTEGER | 0 | 727 | 0 | 2425 | Count of distinct product codes purchased. |
| `average_products_per_order` | DOUBLE | 1,467 | 4,583 | 0.0 | 259.0 | Product lines per order; NaN if no orders. |
| `cancellation_rate` | DOUBLE | 0 | 698 | 0.0 | 1.0 | Cancellation invoices over all invoices, in [0,1]. |
| `repeat_purchase_ratio` | DOUBLE | 1,467 | 183 | 0.0 | 0.9971830985915493 | Share of orders beyond the first, (order_count-1)/order_count; NaN if no orders. |
| `customer_age_days` | INTEGER | 0 | 689 | 1 | 700 | Days from first activity to the cutoff (= tenure). |
| `days_since_last_purchase` | DOUBLE | 2,015 | 686 | 1.0 | 700.0 | Days from the last product purchase to the cutoff; NaN if the customer has never purchased. |

## `gold.labels`

Supervised churn target: one row per active customer (D3, `recency_days ≤ 90` from customer_360) per `snapshot_date`. `churned = 1` when no product purchase falls in `[snapshot, snapshot + 90d)` (D2/D24); rows whose window extends past the observed-data horizon with no purchase are censored (`churned` NULL). The forward window is the only deliberate look-ahead — target only, never features. Profiled in [labels.md](labels.md).

**Rows:** 44,581

| Column | Type | Nulls | Distinct | Min | Max | Description |
|--------|------|-------|----------|-----|-----|-------------|
| `customer_id` | VARCHAR | 0 | 5,722 | 12346 | 18287 | Customer identifier; the D3 active population at the snapshot. |
| `snapshot_date` | DATE | 0 | 21 | 2010-03-01 | 2011-11-01 | Point-in-time labeling cutoff; the forward window starts here (D18). |
| `churned` | INTEGER | 2,109 | 2 | 0 | 1 | 1 if no product purchase in [snapshot, snapshot+90d); 0 if a purchase occurred; NULL when censored (window unobserved). |
| `censored` | BOOLEAN | 0 | 2 | false | true | True when the 90-day window extends past the observed-data horizon and no purchase was seen, so the outcome is unknowable (D4). |
| `next_purchase_date` | DATE | 19,571 | 535 | 2010-03-01 | 2011-12-09 | Date of the first product purchase in the window; null unless churned = 0. |
