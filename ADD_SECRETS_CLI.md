# Add GitHub Secrets via CLI (Fast Method)

## Using GitHub CLI (Recommended for Speed)

If you have `gh` CLI installed, run these commands:

```bash
cd C:\Users\USER\Downloads\Shopify_Claude

# Add Shopify token (REQUIRED)
gh secret set SHOPIFY_ACCESS_TOKEN --body "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"

# Add Gemini API key (RECOMMENDED - get from https://aistudio.google.com/app/apikey)
gh secret set GEMINI_API_KEY --body "your-gemini-key-here"

# Add Groq API key (OPTIONAL - get from https://console.groq.com)
gh secret set GROQ_API_KEY --body "your-groq-key-here"

# Add OpenRouter API key (OPTIONAL - get from https://openrouter.ai/account/api-keys)
gh secret set OPENROUTER_API_KEY --body "your-openrouter-key-here"
```

## Verify Secrets Were Added

```bash
gh secret list
```

You should see:
```
SHOPIFY_ACCESS_TOKEN    Updated 2 minutes ago
GEMINI_API_KEY          Updated 2 minutes ago
GROQ_API_KEY            Updated 2 minutes ago
OPENROUTER_API_KEY      Updated 2 minutes ago
```

## Get API Keys

### 1. Shopify Access Token (Already have: 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)
Already provided ✓

### 2. Gemini API Key (Google AI Studio)
```
Website: https://aistudio.google.com/app/apikey
Steps:
  1. Go to the link above
  2. Click "Create API Key" 
  3. Select "Create API key in new project"
  4. Copy the key
  5. Add to CLI: gh secret set GEMINI_API_KEY --body "your-key"
Free tier: 1M tokens/day
```

### 3. Groq API Key (Optional but recommended)
```
Website: https://console.groq.com/login
Steps:
  1. Sign up or log in
  2. Go to API keys section
  3. Create new API key
  4. Copy the key
  5. Add to CLI: gh secret set GROQ_API_KEY --body "your-key"
Free tier: ~500K tokens/day
```

### 4. OpenRouter API Key (Optional fallback)
```
Website: https://openrouter.ai/account/api-keys
Steps:
  1. Go to account/api-keys
  2. Create new key
  3. Copy the key
  4. Add to CLI: gh secret set OPENROUTER_API_KEY --body "your-key"
Free tier: Unlimited
```

## Quick Setup (Copy-Paste Ready)

Once you have the API keys, run this one command per secret:

**Shopify (REQUIRED):**
```bash
gh secret set SHOPIFY_ACCESS_TOKEN --body "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"
```

**Gemini (RECOMMENDED):**
```bash
gh secret set GEMINI_API_KEY --body "YOUR_GEMINI_KEY_HERE"
```

**Optional but good to have:**
```bash
gh secret set GROQ_API_KEY --body "YOUR_GROQ_KEY_HERE"
gh secret set OPENROUTER_API_KEY --body "YOUR_OPENROUTER_KEY_HERE"
```

## Without gh CLI (Web UI Method)

If you don't have `gh` installed, use the web interface:

1. Go to: https://github.com/meeeshop/meeeshop-invt/settings/secrets/actions
2. Click "New repository secret"
3. Add each secret manually:
   - Name: `SHOPIFY_ACCESS_TOKEN`
   - Value: `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`
4. Click "Add secret"
5. Repeat for each API key

See SETUP_SECRETS.md for detailed web UI instructions.

## Test Secrets Are Working

After adding secrets:

1. Go to Actions tab
2. Select "Daily Price Update" workflow
3. Click "Run workflow"
4. Watch logs for success messages:
   ```
   [AI:Gemini] OK
   [PriceUpdate] Complete: X updated, X skipped
   ```

## Rotate/Update Secrets

To update a secret (e.g., if token expires):

```bash
gh secret set SHOPIFY_ACCESS_TOKEN --body "new-token-here"
```

This overwrites the existing secret.

## Delete Secrets

```bash
gh secret delete SHOPIFY_ACCESS_TOKEN
gh secret delete GEMINI_API_KEY
```

## Security

✓ Secrets are encrypted by GitHub
✓ Never shown in logs or exposed
✓ Only accessible during workflow execution
✓ Can be rotated anytime without downtime
