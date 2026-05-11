# GitHub Secrets Setup Guide

## Required Secrets for Price Update Automation

Go to: **GitHub repo > Settings > Secrets and variables > Actions**

### Add These Secrets:

#### 1. **SHOPIFY_ACCESS_TOKEN** (Required)
- **Value**: `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`
- **Purpose**: Authenticate to Shopify Admin API
- **Get from**: Shopify Admin > Apps & integrations > API credentials
- **Status**: ✓ Ready to add

#### 2. **GEMINI_API_KEY** (Recommended)
- **Value**: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **Purpose**: Primary AI provider for price optimization
- **Free Tier**: 1M tokens/day
- **Status**: Generate at Google AI Studio

#### 3. **GROQ_API_KEY** (Optional)
- **Value**: Get from [Groq Console](https://console.groq.com/login)
- **Purpose**: Fallback AI provider
- **Free Tier**: ~500K tokens/day
- **Status**: Generate at Groq (optional, but recommended)

#### 4. **OPENROUTER_API_KEY** (Optional)
- **Value**: Get from [OpenRouter](https://openrouter.ai/account/api-keys)
- **Purpose**: Final fallback (25+ free models)
- **Free Tier**: Unlimited tokens
- **Status**: Generate at OpenRouter (optional)

## Step-by-Step Setup

### Step 1: Go to Secrets Settings
1. Open: https://github.com/meeeshop/meeeshop-invt/settings/secrets/actions
2. Click **"New repository secret"**

### Step 2: Add SHOPIFY_ACCESS_TOKEN
```
Name:  SHOPIFY_ACCESS_TOKEN
Value: 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
```
Click **"Add secret"**

### Step 3: Add GEMINI_API_KEY
1. Go to https://aistudio.google.com/app/apikey
2. Click **"Create API Key"** → **"Create API Key in new project"**
3. Copy the key
4. Add to GitHub:
```
Name:  GEMINI_API_KEY
Value: [paste key from Google AI Studio]
```
Click **"Add secret"**

### Step 4: (Optional) Add GROQ_API_KEY
1. Go to https://console.groq.com/login
2. Sign up or log in
3. Go to API keys
4. Create new key
5. Add to GitHub:
```
Name:  GROQ_API_KEY
Value: [paste key from Groq]
```
Click **"Add secret"**

### Step 5: (Optional) Add OPENROUTER_API_KEY
1. Go to https://openrouter.ai/account/api-keys
2. Create new key
3. Add to GitHub:
```
Name:  OPENROUTER_API_KEY
Value: [paste key from OpenRouter]
```
Click **"Add secret"**

## Verify Secrets Are Added

```bash
# Check that secrets are in the repo settings
# You should see 1-4 secrets listed:
✓ SHOPIFY_ACCESS_TOKEN
✓ GEMINI_API_KEY (if added)
✓ GROQ_API_KEY (if added)
✓ OPENROUTER_API_KEY (if added)
```

## Which Secrets Are Required?

| Secret | Required | Fallback |
|--------|----------|----------|
| SHOPIFY_ACCESS_TOKEN | ✓ Yes | None (script will fail) |
| GEMINI_API_KEY | Recommended | Uses Groq/OpenRouter |
| GROQ_API_KEY | Optional | Uses OpenRouter/Gemini |
| OPENROUTER_API_KEY | Optional | Uses 2.3x fixed multiplier |

**Minimum**: Just `SHOPIFY_ACCESS_TOKEN` (will use hardcoded multiplier)
**Recommended**: `SHOPIFY_ACCESS_TOKEN` + `GEMINI_API_KEY`
**Optimal**: All four for maximum resilience

## Test the Setup

Once secrets are added:

1. Go to **Actions** tab
2. Select **"Daily Price Update"** workflow
3. Click **"Run workflow"** → **"Run workflow"**
4. Check the logs in 1-2 minutes

You should see:
```
[MeeeShop] Price Update Engine (LIVE mode)
Store: us-meeeshop.myshopify.com
[Fetch] Retrieving active products from Shopify...
[Fetch] Found X products
...
[AI:Gemini] OK
[PriceUpdate] Complete: X updated, X skipped, X errors
```

## Security Notes

- Secrets are **encrypted** by GitHub (never visible in logs)
- Each secret is only accessible by the workflow
- Secrets are **not** committed to git
- You can rotate/revoke secrets anytime from Settings

## Troubleshooting

### "workflow/price_update.yml failed"
→ Check that SHOPIFY_ACCESS_TOKEN is added

### "[AI] all providers failed"
→ At least one AI key is needed (Gemini recommended)
→ Script will fall back to 2.3x multiplier

### "401 Unauthorized"
→ SHOPIFY_ACCESS_TOKEN is invalid or expired
→ Regenerate token in Shopify Admin

## Next: Run the Workflow

After adding secrets:
1. Go to Actions tab
2. Select "Daily Price Update"
3. Click "Run workflow"
4. Monitor logs for results
5. Check Shopify store for price updates

---

**Need help?** Check the README.md in meeeshop-invt folder for detailed docs.
