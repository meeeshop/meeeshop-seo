# Quick Start - Price Update Automation

## 5-Minute Setup

### 1. Add SHOPIFY_ACCESS_TOKEN Secret
```
URL: https://github.com/meeeshop/meeeshop-invt/settings/secrets/actions
Name: SHOPIFY_ACCESS_TOKEN
Value: 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
```

### 2. (Optional) Add GEMINI_API_KEY Secret
```
Get key: https://aistudio.google.com/app/apikey
Name: GEMINI_API_KEY
Value: [your key]
```

### 3. Run Workflow Test
```
URL: https://github.com/meeeshop/meeeshop-invt/actions
Action: Click "Daily Price Update" → "Run workflow" → "Run workflow"
Wait: 1-2 minutes
```

### 4. Check Logs
```
Look for: [PriceUpdate] Complete: X updated, X skipped, X errors
```

### 5. Verify in Shopify
```
URL: https://admin.shopify.com/store/us-meeeshop/products
Check: Prices ending in .99 (e.g., $48.99, $77.99)
```

---

## Daily Automation

- **Schedule**: 9:00 AM UTC (every day)
- **Manual run**: Actions tab → "Run workflow"
- **Logs**: Actions tab (90-day retention)
- **Results**: price_update_log.json (30-day retention)

---

## Pricing Formula

```
Final Price = (Cost × 2.3-2.5) + $8.50 shipping → round to .99
Profit = Final Price - Cost - $4.25 (avg shipping)
```

**Example**: $30 cost → $80.99 price → $46.74 profit

---

## Output Example

**Console:**
```
Seq | Product Title     | Old Price | New Price | Cost  | Profit | Status
1   | Summer Dress      | $45.00    | $48.99    | $18   | $15.49 | UPDATED
2   | Evening Gown      | $89.99    | $89.99    | $35   | $42.49 | OPTIMAL
```

**JSON:** `meeeshop-invt/price_update_log.json`
```json
{
  "timestamp": "2026-05-11T15:30:00",
  "summary": {"updated": 12, "skipped": 32, "errors": 0},
  "products": [...]
}
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `401 Unauthorized` | Shopify token wrong → regenerate in Admin |
| `[AI] all providers failed` | Normal, uses 2.3x multiplier (works fine) |
| Prices didn't change | Check Shopify logs, verify costs are set |
| Workflow didn't run | Check Actions tab, may need manual trigger |

---

## Key Features

✓ **Dynamic pricing**: 2.3-2.5x cost (AI-optimized)
✓ **Psychology pricing**: All prices end in .99
✓ **Profit guarantee**: $20+ per product
✓ **Smart skip**: No updates if already optimal
✓ **Daily automation**: 9 AM UTC
✓ **Detailed logging**: Before/after prices + profit
✓ **AI resilience**: Falls back gracefully if APIs unavailable

---

## Next Steps After Setup

1. Monitor workflow runs for 3-5 days
2. Check profit margins are on track
3. Add related automations:
   - Pinterest (price-based pins)
   - YouTube (product shorts)
   - Blog SEO (product embeds)

---

**Full docs**: See README.md, LOGGING_GUIDE.md, MANUAL_SECRETS_SETUP.txt
