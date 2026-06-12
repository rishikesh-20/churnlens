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
