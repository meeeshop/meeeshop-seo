# SEO Workflow Modes - Quick Reference

## 🚀 Three Execution Modes

| Mode | Command | Schedule | Scope | Best For |
|------|---------|----------|-------|----------|
| **Daily** | `python seo_daily.py --daily` | Every day 6 AM UTC | Last 48h | New/updated products |
| **Weekly** | `python seo_daily.py --weekly` | Sunday 8 AM UTC | Last 7 days | Catch edge cases |
| **Force** | `python seo_daily.py --force` | Manual only | Entire catalog | Store-wide fixes |

---

## ✅ What Each Mode Does

### Daily (48 hours)
```
New/Updated Products → SEO Optimization
├─ Add meta titles & descriptions
├─ Generate SEO product descriptions
├─ Fix image ALT text
├─ Update title case
├─ Normalize handles + create redirects
└─ Skip recently-optimized products
```

### Weekly (Last 7 days)
```
Older Products → Deep Optimization
├─ Add comprehensive descriptions
├─ Fill missing metafields
├─ Ensure size charts included
├─ Complete image ALT coverage
└─ Skip very recent products (let daily handle them)
```

### Force (All products)
```
Entire Catalog → Complete Normalization
├─ Override all SEO fields
├─ Ensure consistency
├─ Update all size charts
├─ Normalize all descriptions
└─ ⚠️ Use only when needed (full store pivot, compliance changes)
```

---

## 📅 Auto-Schedule

**Via GitHub Actions** (`.github/workflows/seo_daily.yml`):

```
6 AM UTC (Mon-Sat)  → Daily mode
8 AM UTC (Sunday)   → Weekly mode
```

**Or manual**: Click "Run workflow" → Select mode

---

## 📊 Output Example

Each run creates `seo_report_YYYYMMDD_HHMM.json`:

```json
{
  "products": 45,
  "descriptions": 38,
  "meta_titles": 45,
  "alts": 120,
  "redirects": 2,
  "mode": "daily",
  "run_at": "2026-05-14T06:00:00Z"
}
```

---

## 🔧 Testing Commands

```bash
# Test daily (5 products only)
python seo_daily.py --daily --limit 5

# Test weekly
python seo_daily.py --weekly --limit 10

# Custom: last 72 hours
python seo_daily.py --hours 72 --limit 5

# Dry run (skip JSON-LD injection)
python seo_daily.py --daily --skip-jsonld
```

---

## 🎯 Recommended Schedule

- **Daily runs**: Automatic (catches new products)
- **Weekly runs**: Automatic (Sunday catches stragglers)
- **Force runs**: Quarterly or when strategy changes
  - Before running: notify team
  - After running: review report before shipping

---

## 📈 Expected Results (per run)

### Daily (48h, ~50 products)
- ~45 descriptions added
- ~45 meta titles/descs set
- ~120 image ALTs fixed
- ~2-3 minutes runtime

### Weekly (7d, ~150 products)
- ~140 descriptions
- ~150 meta fields
- ~300 image ALTs
- ~5-7 minutes runtime

### Force (all, ~1000+ products)
- All products normalized
- Complete catalog audit
- ~15-20 minutes runtime

---

## ⚙️ Environment Setup

**GitHub Secrets Required**:
```
SHOPIFY_STORE = your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN = shpat_xxxxx
```

**Local Testing** (set in terminal):
```bash
export SHOPIFY_STORE=your-store.myshopify.com
export SHOPIFY_ACCESS_TOKEN=shpat_xxxxx
python seo_daily.py --daily --limit 5
```

---

## 🚨 When to Use Force

✅ **Safe to use**:
- Brand rebrand
- Return policy change (7-day → 14-day)
- Major SEO strategy pivot
- Quarterly maintenance

❌ **Don't use for**:
- Quick fixes on one product
- Testing new copy (use --limit with daily instead)
- Every run (defeats the purpose of daily/weekly)

---

## 📝 What Gets Updated

Per product:
- ✅ Meta title (60 chars max)
- ✅ Meta description (155 chars)
- ✅ Product title (title case)
- ✅ Body description (with size chart)
- ✅ Image ALT text (125 chars each)
- ✅ URL handle (if needed)
- ✅ 301 redirect (if handle changes)

Per store (once):
- ✅ JSON-LD schema injection (idempotent)

---

## 📞 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Could not find live theme" | Check Shopify theme settings |
| "Metafields error" | Verify API token has product:write |
| Rate limit slow | Script auto-throttles—check logs |
| ALT text not updating | Verify image exists & token has scope |

---

## 🎯 Next Steps

1. **Deploy**: Add GitHub secrets → enable workflow
2. **Monitor**: Review first report
3. **Adjust**: Modify templates in `seo_daily.py` as needed
4. **Scale**: Once stable, use force mode quarterly
