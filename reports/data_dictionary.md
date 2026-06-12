# Data Dictionary

Generated from the live warehouse on every ingestion run — do not edit by hand.

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
| `loaded_at` | TIMESTAMP | 0 | 1 | 2026-06-12 03:07:23.101187 | 2026-06-12 03:07:23.101187 | Lineage: UTC timestamp of the load run. |
