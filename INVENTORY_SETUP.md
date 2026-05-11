# MeeeShop Inventory Automation — Quick Setup

## What It Does

Automatically updates product prices daily:
- **Multiplier**: 2.3-2.5x cost per item (AI-optimized)
- **Shipping**: +$7-10 USD (built into price)
- **Profit**: Guarantees $20+ per product
- **Psychology Pricing**: All prices end in .99 (70.99, 74.99, etc.)
- **Schedule**: Runs every day at 9 AM UTC via GitHub Actions

## Quick Setup (5 minutes)

### 1. Set GitHub Secrets

Go to your repo → **Settings > Secrets and variables > Actions** → Add these secrets:

| Secret | Value | Source |
|--------|-------|--------|
| `SHOPIFY_ACCESS_TOKEN` | `shpat_...` | Shopify Admin > Apps > API Credentials |
| `GEMINI_API_KEY` | (optional) | Google AI Studio (free tier) |
| `GROQ_API_KEY` | (optional) | groq.com (free tier) |
| `OPENROUTER_API_KEY` | (optional) | openrouter.ai (free tier) |

✓ Only need one AI key minimum (Gemini recommended)

### 2. Verify Daily Schedule

The workflow runs at 9 AM UTC every day. To test:
1. Go to repo → Actions tab
2. Select "Daily Price Update" workflow
3. Click "Run workflow" → "Run workflow"
4. Check logs in 1-2 minutes

### 3. Monitor Runs

Each day's run generates:
- Log file: `meeeshop-invt/price_update_log.json`
- Artifact: Available in Actions tab for 30 days
- Summary: Updated products, skipped, errors

## Testing (Optional)

Run locally before enabling:

```bash
cd meeeshop-invt
python price_update.py --dry-run  # No changes, just show what would happen
```

## Pricing Examples

| Cost | Multiplier | Shipping | Final Price | Profit |
|------|-----------|----------|-------------|--------|
| $10  | 2.5x      | $8.50    | $33.99      | $15.49 |
| $15  | 2.5x      | $8.50    | $46.99      | $28.49 |
| $20  | 2.3x      | $8.50    | $54.99      | $26.49 |
| $30  | 2.4x (AI) | $8.50    | $80.99      | $42.49 |
| $50  | 2.3x      | $8.50    | $123.99     | $65.49 |

## How AI Works

AI suggests optimal multiplier (2.3-2.5) based on cost:
- **Cheap items** ($10-15): Higher multiplier (2.5x) needed for profit
- **Standard items** ($20-50): AI picks 2.3-2.4x for balanced margins
- **Expensive items** ($100+): Lower multiplier (2.3x) for better sales

If AI unavailable (rate-limited), falls back to 2.3x multiplier.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Workflow not running | Check that secrets are set (Settings > Secrets) |
| Price not updating | Run `--dry-run` mode to test logic locally |
| AI provider failing | Try different AI key (script tries all 3 in sequence) |
| Products skipped | If price already optimal, skipped to save API calls |

## Files Overview

```
meeeshop-invt/
├── price_update.py          # Main script (run via GitHub Actions)
├── ai_client.py             # AI provider fallback logic
├── test_pricing.py          # Validation (test without Shopify creds)
├── .env.example             # Template for local testing
├── .github/workflows/
│   └── price_update.yml     # Daily scheduler (9 AM UTC)
├── price_update_log.json    # Log file (created daily)
└── README.md                # Full technical documentation
```

## Next: What's Automated

After daily price updates, you can add:
- Pinterest automation (pin trending products)
- YouTube shorts (product teasers)
- Blog SEO (product embeds)

These integrate with the same inventory data.

---

**Need help?** Check logs in Actions tab or review README.md for detailed API docs.
