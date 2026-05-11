# MeeeShop Inventory Automation

Automated pricing engine for dynamic product price updates based on cost, with AI-powered multiplier optimization.

## Features

- **Dynamic Pricing**: Calculates retail prices using AI-suggested multipliers (2.3-2.5x cost)
- **Psychology Pricing**: Prices end in .99 (e.g., 70.99, 74.99) to maximize perceived value
- **Profit Guarantee**: Ensures $20+ profit per product after shipping costs ($7-10)
- **Smart Skip**: Skips products already at target price (no unnecessary API calls)
- **Daily Automation**: Runs automatically every day at 9 AM UTC via GitHub Actions
- **AI Fallback**: Uses Gemini, Groq, or OpenRouter; fails gracefully if all providers are down

## Setup

### 1. Local Environment

Copy `.env.example` to `.env` and add your credentials:

```bash
cp .env.example .env
```

Fill in:
- `SHOPIFY_ACCESS_TOKEN` from your Shopify Admin API
- AI API keys (at least one of: GEMINI, GROQ, OPENROUTER)

### 2. GitHub Secrets

Add these secrets to your repository settings (`Settings > Secrets and variables > Actions`):

- `SHOPIFY_ACCESS_TOKEN`
- `GEMINI_API_KEY` (optional, but recommended)
- `GROQ_API_KEY` (optional)
- `OPENROUTER_API_KEY` (optional)

## Usage

### Manual Run

```bash
# Test mode (dry-run, no price updates)
python meeeshop-invt/price_update.py --dry-run

# Live mode (updates prices in Shopify)
python meeeshop-invt/price_update.py
```

### Automated Run

The workflow runs daily at **9:00 AM UTC** and can also be triggered manually via `workflow_dispatch`.

Logs are saved to `meeeshop-invt/price_update_log.json` and available as GitHub Actions artifacts.

## Pricing Logic

For each product variant with a cost:

1. **AI Multiplier**: AI suggests optimal multiplier (2.3-2.5x) based on cost
2. **Base Price**: `cost × multiplier + $8.50 (avg shipping)`
3. **Psychology**: Round up to next .99 ending
4. **Profit Check**: Ensure profit >= $20 after shipping

### Example

- Cost: $30
- AI Multiplier: 2.4 (suggested for this price range)
- Base: (30 × 2.4) + 8.50 = $80.50
- Final: $80.99 (next .99 ending)
- Profit: $80.99 - $30 - $8.50 = $42.49 ✓

## Architecture

- `price_update.py` — Main pricing engine + Shopify API integration
- `ai_client.py` — AI provider abstraction (Gemini, Groq, OpenRouter)
- `.github/workflows/price_update.yml` — Daily automation trigger

## Monitoring

### Console Output
Each run displays a detailed table showing:
```
Seq | Product Title              | Old Price | New Price | Cost   | Profit  | Status
----|----------------------------|-----------|-----------|--------|---------|--------
1   | Summer Dress Classic       | $45.00    | $48.99    | $18.00 | $15.49  | UPDATED
2   | Casual T-Shirt             | $22.50    | $23.99    | $8.50  | $10.49  | UPDATED
3   | Evening Gown               | $89.99    | $89.99    | $35.00 | $42.49  | OPTIMAL
```

Status meanings:
- **UPDATED**: Price changed (new calculation applied)
- **OPTIMAL**: Price already at target (no change needed)
- **NO COST**: No cost data (skipped)
- **ERROR**: API call failed

### JSON Log File
Detailed logs saved to `price_update_log.json`:
```json
{
  "timestamp": "2026-05-11T15:30:00.000",
  "summary": {
    "total_products": 45,
    "updated": 12,
    "skipped": 32,
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
    }
  ]
}
```

### GitHub Actions Monitoring
1. Go to **Actions** tab
2. Select **"Daily Price Update"** workflow
3. View logs (console output) and artifacts (JSON logs, 30-day retention)

## Troubleshooting

### AI Provider Failures

The script tries providers in this order:
1. Gemini 2.0 Flash (Google, 1M tokens/day free)
2. Groq Llama-3.3-70B (~500K tokens/day free)
3. OpenRouter free models (25+ models, unlimited)

If all fail, it falls back to hardcoded 2.3x multiplier.

### Missing Credentials

- **Shopify token**: Get from Shopify Admin > Apps & Integrations > API Credentials
- **AI keys**: Sign up free at Google AI Studio, Groq, or OpenRouter

### API Errors

Check workflow logs for:
- Rate limiting (429) — wait, script will retry
- Token limits — skips and moves to next model
- Auth errors — verify secrets are correct

## Next Steps

- [ ] Set up GitHub repository and add secrets
- [ ] Run `--dry-run` to verify pricing logic
- [ ] Trigger first live run
- [ ] Monitor logs for 3-5 days
- [ ] Adjust multiplier ranges if needed
