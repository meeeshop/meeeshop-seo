# MeeeShop SEO Automation v2.0 - Complete Guide

## Overview

Enhanced SEO automation script that optimizes products, collections, pages, and blog posts for Google rankings. Focuses on women shoppers in the USA with proper 7-day return policy messaging and Pinterest/YouTube social links.

### Key Improvements

✅ **Product Descriptions**: Introduction + Features + Why Choose + Size Charts
✅ **Meta Titles**: `Product | Category | us.meeeshop` (max 60 chars)
✅ **Meta Descriptions**: 155 chars, keyword-rich, includes 7-day returns + free shipping
✅ **Image ALT Text**: `[Product] (category) - shop at us.meeeshop` (max 125 chars)
✅ **JSON-LD Schemas**: Product, BreadcrumbList, CollectionPage, LocalBusiness, Organization
✅ **Return Policy**: Consistent "7-day return policy" across all content
✅ **Social Links**: Pinterest & YouTube only (Instagram/TikTok removed)
✅ **Workflow Modes**: Daily (48h), Weekly (7d), Force (full store)

---

## Workflow Modes

### 1. **Daily Mode** (Default)
**Schedule**: Every day at 6:00 AM UTC (1:00 AM EST)
**Scope**: Products updated in last 48 hours
**Use Case**: Catch new products and recent changes

```bash
python seo_daily.py --daily
```

**What it does**:
- Adds/updates meta titles & descriptions
- Generates SEO descriptions with features + size charts
- Fixes image ALT text
- Updates title case
- Normalizes URL handles
- Creates 301 redirects when handles change

---

### 2. **Weekly Mode**
**Schedule**: Every Sunday at 8:00 AM UTC (3:00 AM EST)
**Scope**: Products updated in last 7 days (skip very recent)
**Use Case**: Catch products missed by daily run, add missing descriptions

```bash
python seo_daily.py --weekly
```

**What it does**:
- Processes products updated 24-168 hours ago
- Adds complete product descriptions with size charts
- Ensures all meta fields are filled
- Full image ALT text coverage
- Useful for catching edge cases

---

### 3. **Force Mode** (Use with care!)
**Schedule**: Manual trigger only (no automatic schedule)
**Scope**: Entire product catalog
**Use Case**: Complete store normalization after SEO strategy changes

```bash
python seo_daily.py --force
```

**⚠️ Warning**: 
- Overwrites ALL product metadata
- Only use after confirming changes with team
- Always review JSON report before committing
- Best run during off-peak hours

**What it does**:
- Normalizes ALL product SEO fields
- Ensures consistent branding across catalog
- Fixes any inconsistencies from previous runs
- Updates size charts for all products
- Perfect for strategy pivots or compliance updates

---

## Example Product Output

### Title Case
**Before**: `umgee mix tile print mini dress`
**After**: `Umgee Mix Tile Print Mini Dress`

### Meta Title (60 chars max)
`Umgee Mix Tile Print Mini Dress | Dresses | us.meeeshop`

### Meta Description (155 chars)
```
Discover Umgee Mix Tile Print Mini Dress at us.meeeshop. Quality women's dresses 
with free US shipping & 7-day returns. Affordable, stylish, fast delivery.
```

### Image ALT Text (125 chars max)
`Umgee Mix Tile Print Mini Dress (women's dress) - shop at us.meeeshop`

### Product Description
Includes:
1. **Intro**: Hook with product name + category + free shipping
2. **Features**: 
   - Premium quality materials
   - Stylish design for any occasion
   - Value/quality messaging
   - Free US shipping
   - **7-day return policy**
   - Category-specific messaging
3. **Why Choose**: Why customers should buy at us.meeeshop
4. **Size Chart**: Accurate measurements (S/M/L with bust/waist/hip)

### JSON-LD Schemas

**Product Schema**: Full product data with pricing, availability, offers
**BreadcrumbList**: Home > Category > Product (improves SERP display)
**Organization**: Company info, contact, social links (Pinterest/YouTube)
**LocalBusiness**: Service area, hours, contact (helps local search)

---

## GitHub Actions Workflow

### File: `.github/workflows/seo_daily.yml`

**Auto Schedule**:
- **Daily**: 6:00 AM UTC (Monday-Saturday)
- **Weekly**: 8:00 AM UTC (Sunday)

**Manual Trigger**: Via "Run workflow" → select mode

### Environment Variables (GitHub Secrets)
```
SHOPIFY_STORE = your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN = shpat_xxxxx
```

### Artifacts
Reports saved automatically for 30 days:
- `seo_report_YYYYMMDD_HHMM.json`
- Download from "Artifacts" tab after run

---

## Report Structure

Each report includes:

```json
{
  "products": 45,              // Products updated
  "titles": 12,                // Title case fixes
  "descriptions": 38,          // Descriptions added
  "meta_titles": 45,           // Meta titles set
  "meta_descs": 45,            // Meta descriptions set
  "handles": 2,                // URL handles changed
  "redirects": 2,              // 301 redirects created
  "alts": 120,                 // Image ALT texts fixed
  "mode": "daily",             // Execution mode
  "run_at": "2026-05-14T...",  // Timestamp
  "products_fixed": [
    {
      "product": "Umgee Mix Tile Print Mini Dress",
      "url": "https://us.meeeshop.com/products/umgee-mix-tile-print-mini-dress",
      "missing": ["meta title", "size chart"],
      "fixed": [
        "meta title: 'Women's Dresses | Umgee Mix Tile Print Mini Dress | us.meeeshop'",
        "description: added SEO body with features + size chart",
        "image[0] alt: 'Umgee Mix Tile Print Mini Dress (women's dress) - shop at us.meeeshop'"
      ]
    }
  ]
}
```

---

## Custom Lookback Period

For testing or specific date ranges:

```bash
# Last 72 hours (3 days)
python seo_daily.py --hours 72

# Last 30 days
python seo_daily.py --hours 720
```

---

## Category Detection

Automatically detects product category from title:

| Keywords | Category | Word Form |
|----------|----------|-----------|
| dress, gown, midi, maxi, sundress | Dresses | dress |
| top, blouse, shirt, tee, tank, cami | Tops | top |
| jean, pant, short, legging, jogger | Bottoms | bottom |
| jacket, coat, blazer, sweater, hoodie | Outerwear | layer |
| skirt | Skirts | skirt |
| romper, jumpsuit, bodysuit, playsuit | One-Pieces | one-piece |
| bag, purse, handbag, tote | Bags | bag |
| shoe, boot, heel, sandal, sneaker | Shoes | shoe |
| *default* | Women's Fashion | piece |

Used in meta descriptions, image ALT text, and product descriptions.

---

## Shopify Metafields (SEO)

Updates two key metafields:

1. **global.title_tag** (single_line_text_field)
   - Displays in browser tab & Google results

2. **global.description_tag** (multi_line_text_field)
   - Displays under title in Google results

Both are set via Shopify Admin metafield editor or API.

---

## JSON-LD Theme Injection

**File**: `snippets/meeeshop-jsonld.liquid`
**Location**: Auto-injected into `layout/theme.liquid` before `</head>`

**Idempotent**: Safe to run repeatedly. Uses marker `meeeshop-jsonld v2` to prevent duplicates.

**Schemas Included**:
- Organization (brand + social links)
- LocalBusiness (service area)
- WebSite (search action)
- Product (pricing, offers, ratings)
- BreadcrumbList (navigation)
- CollectionPage (for /collections pages)
- WebPage (for /pages and blog)

---

## 7-Day Return Policy - Key Points

✅ **Everywhere**: Consistently mentioned across:
- Meta descriptions
- Product descriptions
- Footer/CTA text
- Email confirmations
- Return page

✅ **Format**: "7-day return policy" (standardized wording for Google)

✅ **Why**: Builds customer trust for women fashion shoppers

---

## Social Links (Updated)

**Included** (Pinterest & YouTube):
- `https://pinterest.com/meeeshop`
- `https://www.youtube.com/@meeeshop`

**Removed** (no longer in schema):
- Instagram
- TikTok

**Rationale**: Pinterest drives high female traffic, YouTube is important for tutorials/styling. Instagram/TikTok are lower-priority for e-commerce SEO signals.

---

## Running Locally (for testing)

```bash
# Install dependencies
pip install -r requirements.txt

# Load environment variables
export SHOPIFY_STORE=your-store.myshopify.com
export SHOPIFY_ACCESS_TOKEN=shpat_xxxxx

# Test daily mode (limit to 5 products)
python seo_daily.py --daily --limit 5

# Dry run without JSON-LD injection
python seo_daily.py --daily --skip-jsonld

# Force mode (full catalog)
python seo_daily.py --force --limit 10  # Start with limit for testing
```

---

## Performance & API Limits

- **Shopify API**: 40 calls/second (auto-throttles if ≥36 calls used)
- **Rate limiting**: Built-in 0.6s delays when approaching limits
- **Batch size**: 250 products per API page
- **Typical duration**:
  - Daily (50 products): ~2-3 minutes
  - Weekly (150 products): ~5-7 minutes
  - Force (1000+ products): ~15-20 minutes

---

## Troubleshooting

### "Could not find live theme"
- Check Shopify theme settings
- Ensure API token has theme access

### "Metafields error"
- Verify product exists in Shopify
- Check API token permissions

### Rate limit hits
- Script auto-throttles—check logs for "sleeping"
- Reduce batch size with `--limit`

### Image ALT text not updating
- Check product image IDs (must exist)
- Verify API token has product:write scope

---

## Next Steps

1. **Test daily run**: 
   ```bash
   python seo_daily.py --daily --limit 10
   ```

2. **Monitor first report**: Check `seo_report_*.json` output

3. **Deploy to GitHub Actions**:
   - Add SHOPIFY_STORE & SHOPIFY_ACCESS_TOKEN secrets
   - Workflow will run automatically

4. **Weekly review**:
   - Check artifact reports
   - Monitor Google Search Console for ranking changes
   - Adjust keywords if needed

5. **Quarterly force run**:
   - Run `--force` when SEO strategy changes
   - Compare before/after reports

---

## Questions?

Check script comments for implementation details:
- `build_meta_title()` - Meta title logic
- `build_meta_desc()` - Description templates
- `build_alt()` - Image ALT text logic
- `build_description()` - Product body generation
- `detect_cat()` - Category detection from title
