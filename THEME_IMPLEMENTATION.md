# Theme Implementation Guide

## Adding Schema Rendering to Your Shopify Theme

This guide shows you how to add JSON-LD schema rendering to your theme so the validation system's schemas display on your pages.

---

## Option A: Global Implementation (Recommended)

Add this to your theme's main `theme.liquid` file in the `<head>` section:

### Location: Shopify Admin → Themes → Edit Code → `theme.liquid`

Find the closing `</head>` tag and add before it:

```liquid
<!-- Schema.org JSON-LD Rendering -->
{% if product %}
  {% for metafield in product.metafields.json_ld_schema %}
    <script type="application/ld+json">
      {{ metafield.value | json }}
    </script>
  {% endfor %}
{% endif %}

{% if collection %}
  {% for metafield in collection.metafields.json_ld_schema %}
    <script type="application/ld+json">
      {{ metafield.value | json }}
    </script>
  {% endfor %}
{% endif %}

{% if page %}
  {% for metafield in page.metafields.json_ld_schema %}
    <script type="application/ld+json">
      {{ metafield.value | json }}
    </script>
  {% endfor %}
{% endif %}

{% if article %}
  {% for metafield in article.metafields.json_ld_schema %}
    <script type="application/ld+json">
      {{ metafield.value | json }}
    </script>
  {% endfor %}
{% endif %}

<!-- Global Organization Schema -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "MeeeShop",
  "url": "https://us.meeeshop.com",
  "logo": "https://us.meeeshop.com/logo.png",
  "description": "Women's fashion store specializing in dresses, tops, and accessories",
  "sameAs": [
    "https://www.pinterest.com/meeeshop",
    "https://www.youtube.com/@meeeshop"
  ],
  "contactPoint": {
    "@type": "ContactPoint",
    "contactType": "Customer Service",
    "email": "meeeshop17@gmail.com",
    "telephone": "+1-XXX-XXX-XXXX"
  }
}
</script>
```

---

## Option B: Page-Specific Implementation

If you want more control, add to individual template files:

### Product Page: `product.liquid`

```liquid
<!-- Product JSON-LD Schema -->
{% if product.metafields.json_ld_schema.product %}
  <script type="application/ld+json">
    {{ product.metafields.json_ld_schema.product.value | json }}
  </script>
{% endif %}

<!-- Breadcrumb Schema (if breadcrumbs exist) -->
{% if product.metafields.json_ld_schema.breadcrumblist %}
  <script type="application/ld+json">
    {{ product.metafields.json_ld_schema.breadcrumblist.value | json }}
  </script>
{% endif %}
```

### Collection Page: `collection.liquid`

```liquid
<!-- Collection JSON-LD Schema -->
{% if collection.metafields.json_ld_schema.collectionpage %}
  <script type="application/ld+json">
    {{ collection.metafields.json_ld_schema.collectionpage.value | json }}
  </script>
{% endif %}
```

### Page Template: `page.liquid`

```liquid
<!-- Page JSON-LD Schema -->
{% if page.metafields.json_ld_schema.webpage %}
  <script type="application/ld+json">
    {{ page.metafields.json_ld_schema.webpage.value | json }}
  </script>
{% endif %}
```

### Blog Article: `article.liquid`

```liquid
<!-- Blog Post JSON-LD Schema -->
{% if article.metafields.json_ld_schema.blogposting %}
  <script type="application/ld+json">
    {{ article.metafields.json_ld_schema.blogposting.value | json }}
  </script>
{% endif %}
```

---

## Step-by-Step Setup

### 1. Access Theme Code

1. Go to **Shopify Admin** → **Sales channels** → **Online Store**
2. Click **Themes** → **Current Theme** (or your draft theme)
3. Click **Edit code** (or **</> Code** button)

### 2. Find and Edit `theme.liquid`

1. In the file tree on the left, find `theme.liquid` (usually in Layout folder)
2. Click to open
3. Scroll to near the end of the `<head>` section (search for `</head>`)
4. Add the code from **Option A** above just before `</head>`

### 3. Save and Test

1. Click **Save** (top right)
2. Go to a product page on your store
3. Right-click → **View Page Source** (or **Inspect**)
4. Search for `application/ld+json`
5. You should see the schema code

### 4. Validate with Google's Tool

1. Go to [Google Rich Results Test](https://search.google.com/test/rich-results)
2. Paste a product URL from your store
3. Click **Test URL**
4. You should see:
   - ✅ Product snippets detected
   - ✅ Breadcrumbs detected
   - ✅ All schemas valid

---

## Schema Field Reference

The validation system creates these schemas automatically:

### Product Schema
```json
{
  "@type": "Product",
  "name": "Product Title",
  "description": "Product description",
  "image": ["image1.jpg", "image2.jpg"],
  "brand": { "@type": "Brand", "name": "Brand Name" },
  "offers": {
    "@type": "Offer",
    "price": "99.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.5",
    "reviewCount": "42"
  }
}
```

### Collection Schema
```json
{
  "@type": "CollectionPage",
  "name": "Collection Name",
  "description": "Collection description",
  "url": "https://us.meeeshop.com/collections/dresses"
}
```

### Blog Post Schema
```json
{
  "@type": "BlogPosting",
  "headline": "Article Title",
  "description": "Article excerpt",
  "datePublished": "2026-05-15",
  "author": { "@type": "Person", "name": "Author Name" },
  "publisher": {
    "@type": "Organization",
    "name": "MeeeShop"
  }
}
```

---

## Verification Checklist

After adding the code:

- [ ] Code added to `theme.liquid` (in `<head>` section)
- [ ] File saved successfully
- [ ] Product page loads without errors
- [ ] Page source contains `<script type="application/ld+json">`
- [ ] Google Rich Results Test shows valid schemas
- [ ] Schema validation workflow runs successfully

---

## Troubleshooting

### Issue: Schemas not showing in page source

**Problem:** Added code to theme but `<script type="application/ld+json">` not in HTML

**Solution:**
1. Clear browser cache (Ctrl+Shift+Delete)
2. Hard refresh page (Ctrl+Shift+R)
3. Check that theme is set as **Active** (not draft)
4. Verify you saved the file (green checkmark appears)

### Issue: Schemas show but with empty values

**Problem:** `<script type="application/ld+json">{{ metafield.value }}</script>` shows empty

**Solution:**
1. Run schema validation script first
2. Wait 1-2 minutes for metafields to sync
3. Hard refresh the page
4. Check in Shopify Admin → Resources → Products → Edit product → Metafields tab (look for `json_ld_schema` namespace)

### Issue: "Liquid error: undefined method 'json_ld_schema'"

**Problem:** Metafield namespace doesn't exist

**Solution:**
1. This is expected until first validation run
2. Run: `python schema_validator.py --force`
3. Wait for completion
4. Refresh theme page
5. Schemas should now render

### Issue: Google Rich Results Test shows errors

**Problem:** Schema validation test fails

**Solution:**
1. Check error message (usually missing field)
2. Download schema_report JSON from GitHub Actions
3. Look at the specific product/page that failed
4. Check logs for error details
5. File issue if schema generation is wrong

---

## Advanced: Custom Schema Fields

If you want to add custom fields to schemas (beyond what the validator creates), you can:

### Option 1: Extend via Liquid

Add additional schema details in your theme:

```liquid
<!-- Enhanced Product Schema with Custom Fields -->
{% capture product_schema %}
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "{{ product.title }}",
  "description": "{{ product.description | strip_html }}",
  "image": {{ product.featured_image | image_url | json }},
  "price": "{{ product.price | money: settings.currency }}",
  "priceCurrency": "USD",
  "availability": "https://schema.org/InStock",
  "offers": {
    "@type": "AggregateOffer",
    "priceCurrency": "USD",
    "lowPrice": "{{ product.price_min }}",
    "highPrice": "{{ product.price_max }}",
    "offerCount": "{{ product.variants.size }}"
  }
}
{% endcapture %}

<script type="application/ld+json">
{{ product_schema | strip_newlines }}
</script>
```

### Option 2: Extend via Metafield Value

Edit product metafield in Shopify Admin and add extra fields:

1. Product → Edit → Scroll to Metafields
2. Find `json_ld_schema` → `product`
3. Click edit
4. Add extra fields like `keywords`, `review`, `warranty`, etc.

---

## Performance Impact

Adding schema rendering has **minimal performance impact**:

- **Script size:** ~500 bytes per product (minimal)
- **Load impact:** None (scripts are non-blocking)
- **Parsing impact:** Negligible (JSON parsing is fast)
- **SEO benefit:** Significant (rich snippets, better visibility)

The JSON-LD is for search engines, not users, so performance is excellent.

---

## Questions?

1. **Schema not rendering?** Check browser console for JavaScript errors
2. **Metafields empty?** Run validation script first
3. **Google shows errors?** Check schema report JSON for details
4. **Performance concerns?** Schema rendering has zero impact on page speed

See [SCHEMA_VALIDATION_SETUP.md](SCHEMA_VALIDATION_SETUP.md) for detailed troubleshooting.
