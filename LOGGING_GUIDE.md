# Price Update Logging Guide

## Overview

The price update script provides **dual-level logging**:
1. **Console output**: Real-time, human-readable table format
2. **JSON log file**: Detailed product-level data for analysis

Both show the complete pricing transformation for every product.

## Console Output Format

### Table Columns

```
Seq  | Product Title | Old Price | New Price | Cost  | Profit | Status
```

| Column | Meaning | Example |
|--------|---------|---------|
| **Seq** | Sequential product number | 1, 2, 3... |
| **Product Title** | Product name (truncated to 32 chars) | "Summer Dress Classic" |
| **Old Price** | Current Shopify price before update | $45.00 |
| **New Price** | Calculated target price | $48.99 |
| **Cost** | Wholesale/supplier cost | $18.00 |
| **Profit** | Estimated profit after shipping | $15.49 |
| **Status** | What happened to this product | UPDATED |

### Status Values

| Status | Meaning | Reason |
|--------|---------|--------|
| **UPDATED** | Price was changed in Shopify | New calculation differs from current price |
| **OPTIMAL** | Price unchanged (no update needed) | Already matches target price within $0.01 |
| **NO COST** | Product skipped | No cost data available (can't calculate price) |
| **ERROR** | Update failed | Shopify API error or validation issue |
| **DRY-RUN** | Would be updated (test mode) | Shown when running with `--dry-run` flag |

### Example Run Output

```
Seq  | Product Title                     | Old Price | New Price | Cost   | Profit  | Status
-----|--------------------------|-----------|-----------|--------|---------|--------
1    | Summer Dress Classic           | $45.00     | $48.99     | $18.00   | $15.49   | UPDATED
2    | Casual T-Shirt                 | $22.50     | $23.99     | $8.50    | $10.49   | UPDATED
3    | Designer Jeans                 | —          | —          | —        | —        | NO COST
4    | Evening Gown                   | $89.99     | $89.99     | $35.00   | $42.49   | OPTIMAL
5    | Casual Blazer                  | $55.00     | $56.99     | $22.00   | $24.49   | UPDATED
6    | Premium Scarf                  | $35.00     | ERROR      | $14.00   | —        | ERROR

[PriceUpdate] Complete: 3 updated, 2 skipped, 1 error
```

## JSON Log File

### File Location

```
meeeshop-invt/price_update_log.json
```

### File Structure

```json
[
  {
    "timestamp": "2026-05-11T15:30:00.123456",
    "summary": {
      "total_products": 6,
      "updated": 3,
      "skipped": 2,
      "errors": 1
    },
    "products": [
      {
        "sku": "SD-001",
        "title": "Summer Dress Classic",
        "old_price": 45.00,
        "new_price": 48.99,
        "cost": 18.00,
        "profit": 15.49,
        "status": "updated"
      },
      {
        "sku": "DJ-003",
        "title": "Designer Jeans",
        "old_price": null,
        "new_price": null,
        "cost": null,
        "profit": null,
        "status": "skipped_no_cost"
      }
    ]
  },
  {
    "timestamp": "2026-05-12T15:30:00.123456",
    ...next day's data...
  }
]
```

### Summary Fields

| Field | Meaning |
|-------|---------|
| **timestamp** | When the update ran (ISO 8601 format) |
| **total_products** | Total products processed |
| **updated** | Count of prices that changed |
| **skipped** | Count of prices that were skipped (optimal/no cost) |
| **errors** | Count of failed updates |

### Product Fields

| Field | Meaning | Type | Notes |
|-------|---------|------|-------|
| **sku** | Product SKU/identifier | string | Used to match back to Shopify |
| **title** | Product name | string | Full product title |
| **old_price** | Price before update | number / null | Null if skipped_no_cost |
| **new_price** | Calculated target price | number / null | Null if skipped_no_cost |
| **cost** | Wholesale cost | number / null | Null if skipped_no_cost |
| **profit** | Estimated profit | number / null | Calculated as: new_price - cost - (shipping/2) |
| **status** | Update status | string | See status values below |

### Product Status Values

| Status | Meaning |
|--------|---------|
| `updated` | Price changed in Shopify |
| `skipped_optimal` | Already at target price |
| `skipped_no_cost` | No cost data available |
| `error` | API call failed |
| `dry_run` | Would be updated (test mode) |

## Reading the Logs

### Quick Check
Look at the bottom line of console output:
```
[PriceUpdate] Complete: 3 updated, 2 skipped, 0 errors
```

### Detailed Analysis
Open `price_update_log.json` in a JSON viewer or text editor to see:
- Exact prices before and after
- Profit per product
- Which products changed vs. stayed the same
- Errors and why they occurred

### Historical Tracking
The JSON file is **appended to** each day, so you can:
- Compare pricing trends (is profit margin consistent?)
- Identify problem products (multiple errors?)
- Validate profit goals are being met
- Track pricing strategy effectiveness

## Examples

### Example 1: Successful Price Increase

```
Console:
1 | Summer Dress Classic | $45.00 | $48.99 | $18.00 | $15.49 | UPDATED

JSON:
{
  "sku": "SD-001",
  "title": "Summer Dress Classic",
  "old_price": 45.00,
  "new_price": 48.99,
  "cost": 18.00,
  "profit": 15.49,
  "status": "updated"
}
```

**Interpretation**: Product was $45, now $48.99 (2.72x cost multiplier). Customer pays $3.99 more, MeeeShop profits $15.49.

### Example 2: Already Optimal Price

```
Console:
4 | Evening Gown | $89.99 | $89.99 | $35.00 | $42.49 | OPTIMAL

JSON:
{
  "sku": "EG-004",
  "title": "Evening Gown",
  "old_price": 89.99,
  "new_price": 89.99,
  "cost": 35.00,
  "profit": 42.49,
  "status": "skipped_optimal"
}
```

**Interpretation**: Product already priced optimally (no change). Profit of $42.49 confirmed.

### Example 3: Missing Cost Data

```
Console:
3 | Designer Jeans | — | — | — | — | NO COST

JSON:
{
  "sku": "DJ-003",
  "title": "Designer Jeans",
  "old_price": null,
  "new_price": null,
  "cost": null,
  "profit": null,
  "status": "skipped_no_cost"
}
```

**Interpretation**: No cost data in Shopify for this product. Add cost in Shopify Admin, then re-run.

## Monitoring in GitHub Actions

### View Real-Time Logs

1. Go to **Actions** tab in GitHub
2. Click **"Daily Price Update"** workflow
3. Click the latest run
4. View console output with real-time table
5. Scroll to bottom for summary

### Download Artifacts

1. Same run page, scroll down to **Artifacts**
2. Download `price-update-logs` ZIP file
3. Extract `price_update_log.json`
4. Open in text editor or JSON viewer

### Retention

- Console logs: Available for 90 days
- JSON artifacts: Available for 30 days (configurable)

## Profit Calculation

The profit shown is calculated as:

```
Profit = Final Price - Cost - (Avg Shipping Cost)
```

Where:
- **Final Price** = 2.3-2.5x cost, rounded up to .99 ending
- **Cost** = Wholesale/supplier cost from Shopify
- **Avg Shipping Cost** = ($7 + $10) / 2 = $8.50

### Example Calculation

```
Product: Summer Dress
Cost: $18.00
Multiplier: 2.3x
Shipping: $8.50

Raw price = (18 × 2.3) + 8.5 = $49.90
Final price = $49.99 (psychology .99 ending)
Profit = $49.99 - $18.00 - $8.50 = $23.49
```

## Troubleshooting Using Logs

### Problem: Many "NO COST" entries

**Solution**: Add cost data in Shopify Admin
- Products > Product > Variant > Edit > Cost per item

### Problem: Many "ERROR" entries

**Solution**: Check API token
- Logs will show "HTTP 401" or "Unauthorized"
- Regenerate token in Shopify Admin > Apps > API Credentials

### Problem: Profit lower than expected

**Solution**: Check cost data accuracy
- Verify costs in Shopify match actual supplier prices
- High cost = lower profit margin

### Problem: Prices not changing as expected

**Check status field**:
- If "skipped_optimal": Price is already correct
- If "updated": Price should have changed (check Shopify)
- If "error": Something went wrong (check error message)

## Exporting for Analysis

### Convert JSON to CSV

```python
import json
import csv

with open('price_update_log.json') as f:
    data = json.load(f)

# Get all products from all runs
all_products = []
for run in data:
    all_products.extend(run['products'])

# Write CSV
with open('pricing_analysis.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=all_products[0].keys())
    writer.writeheader()
    writer.writerows(all_products)
```

## Best Practices

1. **Review daily**: Check logs each morning to ensure updates ran correctly
2. **Monitor profit**: Verify profit margins are on track
3. **Check errors**: Address any errors immediately (missing cost data, etc.)
4. **Archive logs**: Keep JSON logs as historical records
5. **Validate prices**: Spot-check a few products in Shopify to confirm

---

**Need help?** Check console output for immediate feedback, or examine JSON file for detailed product-level analysis.
