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
| `total_net_revenue` | DOUBLE | 0 | 30,615 | -1663.0600000000002 | 551592.02 | Net product revenue to date in GBP (cancellations net out; non-product codes excluded, D11). May be negative. |
| `trailing_12m_net_revenue` | DOUBLE | 0 | 34,213 | -9854.030000000002 | 318751.33999999997 | Net product revenue in the trailing 12 months before the cutoff, feeding the D6 run rate. |
| `cancelled_revenue` | DOUBLE | 0 | 4,801 | -77621.14000000001 | 0.0 | Net revenue of cancellation lines in GBP (≤ 0). |
| `run_rate_90d` | DOUBLE | 0 | 63,189 | -2429.7608219178087 | 102284.44 | Expected 90-day net revenue (D6): trailing-12m scaled by 90/365, or a full-history rate floored at the churn window for <12mo customers. |
| `country` | VARCHAR | 0 | 41 | Australia | West Indies | Country on the customer's most recent invoice before the cutoff. |

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
