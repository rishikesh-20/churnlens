# Data Quality Report

Generated from the live warehouse on every silver build — do not edit by hand.

## Row accounting (bronze → silver)

Cleaning rules remove only *known* dirt; anything else fails the Pandera
contract below and aborts the build without writing the table.

| Stage | Rows | Dropped | Rule |
|-------|------|---------|------|
| `bronze.transactions` | 1,067,371 | — | raw load |
| after dedup | 1,044,848 | 22,523 | identical rows present in both workbook sheets (export overlap) keep only the earlier sheet's copies |
| after anonymous filter | 809,561 | 235,287 | rows without `customer_id` dropped — churn is per-customer |
| `silver.transactions` | 809,561 | — | published |

## Silver summary

- **Customers:** 5,942
- **Invoices:** 44,876
- **Date range:** 2009-12-01 07:45:00 → 2011-12-09 12:50:00
- **Cancellation lines:** 18,446 (kept as negative quantities; revenue is net)
- **Non-product lines:** 3,673 (kept for activity, excluded from revenue)
- **Zero-price lines:** 70 (kept: real activity, zero revenue)
- **Net product revenue:** £16,411,916.58

## Non-product stock codes (excluded from revenue)

A stock code is a product iff it matches `^\d{5}[A-Za-z]*$`
(five digits plus optional letter suffix). Everything else is a
service/adjustment code, flagged `is_product = false`:

| Stock code | Lines | Net line revenue |
|------------|-------|------------------|
| `M` | 1,096 | £-185,325.48 |
| `POST` | 1,983 | £110,338.51 |
| `D` | 170 | £-12,785.34 |
| `C2` | 254 | £12,271.00 |
| `DOT` | 16 | £11,906.36 |
| `CRUK` | 16 | £-7,933.43 |
| `ADJUST` | 61 | £2,038.12 |
| `ADJUST2` | 3 | £731.05 |
| `BANK CHARGES` | 37 | £330.00 |
| `TEST001` | 15 | £202.50 |
| `PADS` | 19 | £-36.58 |
| `SP1002` | 2 | £14.75 |
| `TEST002` | 1 | £1.00 |

## Silver contract (Pandera, enforced on every build)

| Column | Type | Nullable | Checks |
|--------|------|----------|--------|
| `invoice` | string[python] | no | `str_matches('^C?\d{6}$')` |
| `stock_code` | string[python] | no | — |
| `description` | string[python] | no | — |
| `quantity` | int64 | no | `not_equal_to(0)` |
| `invoice_date` | datetime64[ns] | no | `greater_than_or_equal_to(2009-12-01 00:00:00)`; `less_than(2012-01-01 00:00:00)` |
| `unit_price` | float64 | no | `greater_than_or_equal_to(0)` |
| `customer_id` | string[python] | no | `str_matches('^\d{5}$')` |
| `country` | string[python] | no | — |
| `line_revenue` | float64 | no | — |
| `is_cancellation` | bool | no | — |
| `is_product` | bool | no | — |
| `source_file` | string[python] | no | — |
| `source_sheet` | string[python] | no | — |
| `loaded_at` | datetime64[ns] | no | — |

Frame-level business rules:

- line_revenue must equal quantity * unit_price
- cancellations must be exactly the negative-quantity rows
- is_cancellation must mirror the 'C' invoice prefix
- is_product must mirror the structural stock-code rule
