# Internal Linker — Automated Internal Linking

Automatically injects links between blog posts, products, and collections.

## What It Does

Scans blog articles for keywords (product names, collection names, article titles) that aren't already linked, then injects `<a>` tags to relevant pages.

**Example:**
- Article mentions "summer dress" → links to `/products/summer-dress`
- Article mentions "styling tips" → links to related blog post
- Article mentions "date night" → links to `/collections/date-night-looks`

## Usage

```bash
# Preview links for articles created last 7 days
python internal_linker.py --weekly --dry-run

# Actually inject links
python internal_linker.py --weekly --apply

# Full store (all articles)
python internal_linker.py --force --apply

# Force mode with batching (GitHub Actions)
python internal_linker.py --force --apply --batch-size 100 --batch-index 0
```

## Logging

Script outputs detailed logs showing:
- Which article was processed
- Which keywords were found (and how many times)
- Which URLs were linked to
- Whether links were injected or skipped

**Log files:**
- `internal_linker_run_TIMESTAMP.log` — execution log
- `internal_linker_report_TIMESTAMP.json` — structured report with all links injected

**JSON Report includes:**
```json
{
  "articles_processed": 42,
  "links_injected": 156,
  "detailed_log": [
    {
      "article_title": "5 Summer Outfit Ideas",
      "article_url": "https://us.meeeshop.com/blogs/style/summer-outfits",
      "links_injected": [
        {
          "keyword": "floral dress",
          "target_url": "https://us.meeeshop.com/products/floral-midi-dress",
          "occurrences_in_article": 3
        }
      ]
    }
  ]
}
```

## GitHub Actions Workflow

**File:** `.github/workflows/internal_linker.yml`

### Automatic Schedule
- **Weekly:** Sunday 7:00 AM UTC (links articles from last 7 days)

### Manual Dispatch
Run > Actions > Internal Link Builder > Inputs:
- `weekly` — links articles from last 7 days
- `force` — links all articles (batched)

### Force Mode
- Automatically counts total articles
- Splits into batches of 100
- Runs sequentially (max-parallel: 1) to avoid Shopify rate limits
- Each batch generates its own report + log

## How It Works

1. **Build link map** — Fetches all products, collections, articles → extracts keywords
2. **Scan articles** — For each article, finds keywords not already in links
3. **Inject links** — Replaces first occurrence of unlinked keyword with `<a href>` tag
4. **Validate** — Never re-links existing links, respects HTML structure
5. **Log & report** — Detailed logs + JSON report per run

## Testing

```bash
# Dry-run first to see what would be linked
python internal_linker.py --weekly --dry-run

# Review the log and report
# If looks good:
python internal_linker.py --weekly --apply
```

Check artifacts in GitHub Actions for full reports.
