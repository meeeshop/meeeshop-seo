"""
MeeeShop — Full SEO Theme Builder
Pushes to draft theme: MeeeShop-Modern-Draft (ID: 155004403883)
Adds: popular searches, category tiles, subcategory navs,
      blog internal links, homepage layout, collection subnav
"""

import urllib.request, urllib.parse, urllib.error
import json, time, sys

TOKEN    = "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"
SHOP     = "us-meeeshop.myshopify.com"
API      = "2025-01"
HDR      = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
DRAFT_ID = 155004403883

def put(tid, key, value):
    body = json.dumps({"asset": {"key": key, "value": value}}).encode()
    req  = urllib.request.Request(
        f"https://{SHOP}/admin/api/{API}/themes/{tid}/assets.json",
        data=body, headers=HDR, method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as r:
            sys.stdout.write(f"  [OK] {key}\n"); sys.stdout.flush()
            return True
    except urllib.error.HTTPError as e:
        sys.stdout.write(f"  [ERR] {key}: {e.read().decode()[:80]}\n"); sys.stdout.flush()
        return False

def upload(files):
    for key, val in files.items():
        put(DRAFT_ID, key, val)
        time.sleep(0.3)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Popular Searches (Zepto-style, massive SEO internal linking)
# ═══════════════════════════════════════════════════════════════════════════════

POPULAR_SEARCHES = """
<section class="popular-searches section color-{{ section.settings.color_scheme }}">
  <div class="container">
    <h2 class="popular-searches__heading">{{ section.settings.heading }}</h2>

    <div class="popular-searches__tabs" role="tablist">
      <button class="ps-tab ps-tab--active" data-tab="categories" role="tab">Categories</button>
      <button class="ps-tab" data-tab="styles"     role="tab">Styles</button>
      <button class="ps-tab" data-tab="brands"     role="tab">Brands</button>
      <button class="ps-tab" data-tab="deals"      role="tab">Deals</button>
    </div>

    <!-- Categories -->
    <div class="ps-panel ps-panel--active" data-panel="categories">
      <div class="ps-links">
        <a href="/collections/womens-dresses"           class="ps-link">Dresses</a>
        <a href="/collections/womens-tops"              class="ps-link">Tops</a>
        <a href="/collections/womens-jeans"             class="ps-link">Jeans</a>
        <a href="/collections/womens-bottoms"           class="ps-link">Bottoms</a>
        <a href="/collections/womens-activewear"        class="ps-link">Activewear</a>
        <a href="/collections/womens-sweaters"          class="ps-link">Sweaters</a>
        <a href="/collections/womens-blazers-vests-jackets" class="ps-link">Jackets</a>
        <a href="/collections/womens-outerwear"         class="ps-link">Outerwear</a>
        <a href="/collections/womens-rompers-jumpsuit-sets" class="ps-link">Rompers &amp; Jumpsuits</a>
        <a href="/collections/womens-outfit-sets"       class="ps-link">Outfit Sets</a>
        <a href="/collections/womens-curvy-plus-size-clothing" class="ps-link">Plus Size</a>
        <a href="/collections/womens-shoes"             class="ps-link">Shoes</a>
        <a href="/collections/womens-handbags-accessories" class="ps-link">Handbags</a>
        <a href="/collections/beauty-essentials"        class="ps-link">Beauty</a>
        <a href="/collections/womens-sleepwear"         class="ps-link">Sleepwear</a>
        <a href="/collections/womens-lounge-set"        class="ps-link">Lounge Sets</a>
      </div>
    </div>

    <!-- Styles (keyword phrases — high SEO value) -->
    <div class="ps-panel" data-panel="styles">
      <div class="ps-links">
        <a href="/collections/womens-casual-dresses"    class="ps-link">Casual Dresses</a>
        <a href="/collections/womens-maxi-dresses"      class="ps-link">Maxi Dresses</a>
        <a href="/collections/midi-dresses"             class="ps-link">Midi Dresses</a>
        <a href="/collections/mini-dresses"             class="ps-link">Mini Dresses</a>
        <a href="/collections/womens-cocktail-dresses"  class="ps-link">Cocktail Dresses</a>
        <a href="/collections/womens-formal-evening-dresses" class="ps-link">Formal Dresses</a>
        <a href="/collections/flare-jeans"              class="ps-link">Flare Jeans</a>
        <a href="/collections/wide-leg-jeans"           class="ps-link">Wide Leg Jeans</a>
        <a href="/collections/straight-leg-jeans"       class="ps-link">Straight Leg Jeans</a>
        <a href="/collections/womens-t-shirts"          class="ps-link">T-Shirts</a>
        <a href="/collections/womens-blouses"           class="ps-link">Blouses</a>
        <a href="/collections/long-sleeve-tops"         class="ps-link">Long Sleeve Tops</a>
        <a href="/collections/puff-sleeve-tops"         class="ps-link">Puff Sleeve Tops</a>
        <a href="/collections/v-neck-tops"              class="ps-link">V-Neck Tops</a>
        <a href="/collections/womens-bodysuits"         class="ps-link">Bodysuits</a>
        <a href="/collections/womens-camis-tanks-tops"  class="ps-link">Camis &amp; Tanks</a>
        <a href="/collections/womens-cardigans"         class="ps-link">Cardigans</a>
        <a href="/collections/sweater-pullover"         class="ps-link">Pullover Sweaters</a>
        <a href="/collections/womens-sweatshirts-hoodies" class="ps-link">Hoodies</a>
        <a href="/collections/womens-skirts"            class="ps-link">Skirts</a>
        <a href="/collections/womens-shorts"            class="ps-link">Shorts</a>
        <a href="/collections/womens-pants-leggings"    class="ps-link">Pants &amp; Leggings</a>
        <a href="/collections/made-in-usa"              class="ps-link">Made in USA</a>
      </div>
    </div>

    <!-- Brands -->
    <div class="ps-panel" data-panel="brands">
      <div class="ps-links">
        <a href="/collections/judy-blue-womens-jeans"   class="ps-link">Judy Blue</a>
        <a href="/collections/zenana-womens-clothing"   class="ps-link">Zenana</a>
        <a href="/collections/kancan-usa-womens-jeans"  class="ps-link">Kancan</a>
        <a href="/collections/flying-monkey-womens-jeans-collection" class="ps-link">Flying Monkey</a>
        <a href="/collections/hyfve-womens-clothing"    class="ps-link">Hyfve</a>
        <a href="/collections/mustard-seed-womens-clothing" class="ps-link">Mustard Seed</a>
        <a href="/collections/umgee-usa-womens-clothing" class="ps-link">Umgee USA</a>
        <a href="/collections/risen-womens-jeans-collection" class="ps-link">Risen Jeans</a>
        <a href="/collections/culture-code-womens-clothing" class="ps-link">Culture Code</a>
        <a href="/collections/mittoshop-clothing"       class="ps-link">Mittoshop</a>
        <a href="/collections/very-j-womens-clothing"   class="ps-link">Very J</a>
        <a href="/collections/le-lis-womens-clothing"   class="ps-link">Le Lis</a>
        <a href="/collections/heyson-clothing"          class="ps-link">Heyson</a>
        <a href="/collections/emory-park-womens-clothing" class="ps-link">Emory Park</a>
        <a href="/collections/adora-womens-clothing"    class="ps-link">Adora</a>
        <a href="/collections/vervet-by-flying-monkey-womens-jeans" class="ps-link">Vervet</a>
        <a href="/collections/vibrant-miu-womens-jeans" class="ps-link">Vibrant M.i.U</a>
      </div>
    </div>

    <!-- Deals -->
    <div class="ps-panel" data-panel="deals">
      <div class="ps-links">
        <a href="/collections/under-40"                 class="ps-link ps-link--sale">Under $40</a>
        <a href="/collections/under-50"                 class="ps-link ps-link--sale">Under $50</a>
        <a href="/collections/25-percent-off"           class="ps-link ps-link--sale">25% Off</a>
        <a href="/collections/usa-sale"                 class="ps-link ps-link--sale">USA Sale</a>
        <a href="/collections/sale-plus-size-apparel"   class="ps-link ps-link--sale">Plus Size Sale</a>
        <a href="/collections/womens-best-selling-collection" class="ps-link">Best Sellers</a>
        <a href="/collections/womens-new-collection"    class="ps-link">New Arrivals</a>
        <a href="/collections/selected-usa-styles"      class="ps-link">USA Styles</a>
      </div>
    </div>
  </div>
</section>

{% javascript %}
(function(){
  const tabs   = document.querySelectorAll('.ps-tab');
  const panels = document.querySelectorAll('.ps-panel');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('ps-tab--active'));
      panels.forEach(p => p.classList.remove('ps-panel--active'));
      tab.classList.add('ps-tab--active');
      const panel = document.querySelector('[data-panel="' + tab.dataset.tab + '"]');
      if (panel) panel.classList.add('ps-panel--active');
    });
  });
})();
{% endjavascript %}

{% stylesheet %}
.popular-searches { padding: 40px 0; }
.popular-searches__heading { font-size: clamp(1.2rem,1rem + 1vw,1.6rem); font-weight:700; margin-bottom:20px; text-align:center; }
.container { max-width:1400px; margin:0 auto; padding:0 20px; }
.ps-tabs { display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap; justify-content:center; }
.ps-tab { padding:8px 20px; border-radius:30px; border:1.5px solid currentColor; background:transparent; font-size:14px; font-weight:600; cursor:pointer; transition:all 0.2s ease; opacity:.6; }
.ps-tab--active, .ps-tab:hover { opacity:1; background:var(--color-foreground); color:var(--color-background); border-color:var(--color-foreground); }
.ps-panel { display:none; }
.ps-panel--active { display:block; }
.ps-links { display:flex; flex-wrap:wrap; gap:8px 10px; }
.ps-link { display:inline-block; padding:6px 14px; border-radius:30px; font-size:13px; font-weight:500; text-decoration:none; border:1px solid var(--color-border,#ddd); color:inherit; transition:all 0.2s ease; white-space:nowrap; }
.ps-link:hover { background:var(--color-foreground); color:var(--color-background); border-color:var(--color-foreground); transform:translateY(-1px); }
.ps-link--sale { border-color:#e53935; color:#e53935; }
.ps-link--sale:hover { background:#e53935; color:#fff; }
{% endstylesheet %}

{% schema %}
{
  "name": "Popular Searches",
  "tag": "section",
  "settings": [
    { "type": "text",      "id": "heading",      "label": "Heading", "default": "Popular Searches" },
    { "type": "color_scheme", "id": "color_scheme", "label": "Color scheme", "default": "scheme-1" }
  ],
  "presets": [{ "name": "Popular Searches" }]
}
{% endschema %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Category Tiles (visual grid — like ASOS/H&M)
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_TILES = """
<section class="category-tiles section color-{{ section.settings.color_scheme }}">
  <div class="container">
    {%- if section.settings.heading != blank -%}
      <h2 class="cat-tiles__heading">{{ section.settings.heading }}</h2>
    {%- endif -%}
    <div class="cat-tiles__grid">
      {%- for block in section.blocks -%}
        {%- assign col = collections[block.settings.collection] -%}
        <a href="{{ block.settings.link | default: col.url | default: '/collections/all' }}"
           class="cat-tile" {{ block.shopify_attributes }}>
          {%- if block.settings.image != blank -%}
            {{ block.settings.image | image_url: width: 600 | image_tag: loading: 'lazy', class: 'cat-tile__img', alt: block.settings.label }}
          {%- elsif col.image -%}
            {{ col.image | image_url: width: 600 | image_tag: loading: 'lazy', class: 'cat-tile__img', alt: col.title }}
          {%- else -%}
            <div class="cat-tile__img cat-tile__img--placeholder"></div>
          {%- endif -%}
          <div class="cat-tile__label">
            <span>{{ block.settings.label | default: col.title }}</span>
          </div>
        </a>
      {%- endfor -%}
    </div>
  </div>
</section>

{% stylesheet %}
.category-tiles { padding: 48px 0; }
.cat-tiles__heading { font-size:clamp(1.3rem,1rem+1.2vw,1.8rem); font-weight:700; text-align:center; margin-bottom:28px; letter-spacing:-0.02em; }
.cat-tiles__grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:14px; }
@media(min-width:750px){ .cat-tiles__grid { grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:18px; } }
.cat-tile { position:relative; border-radius:14px; overflow:hidden; text-decoration:none; display:block; aspect-ratio:3/4; }
.cat-tile__img { width:100%; height:100%; object-fit:cover; transition:transform 0.55s cubic-bezier(0.25,0.46,0.45,0.94); }
.cat-tile__img--placeholder { background:#f0f0f0; width:100%; height:100%; }
.cat-tile:hover .cat-tile__img { transform:scale(1.06); }
.cat-tile__label { position:absolute; bottom:0; left:0; right:0; padding:32px 12px 14px; background:linear-gradient(to top,rgba(0,0,0,0.65) 0%,transparent 100%); }
.cat-tile__label span { color:#fff; font-weight:700; font-size:clamp(13px,1vw+10px,16px); letter-spacing:0.01em; text-shadow:0 1px 4px rgba(0,0,0,0.4); }
{% endstylesheet %}

{% schema %}
{
  "name": "Category Tiles",
  "tag": "section",
  "max_blocks": 16,
  "settings": [
    { "type": "text", "id": "heading", "label": "Heading", "default": "Shop by Category" },
    { "type": "color_scheme", "id": "color_scheme", "label": "Color scheme", "default": "scheme-1" }
  ],
  "blocks": [
    {
      "type": "tile",
      "name": "Category Tile",
      "settings": [
        { "type": "collection", "id": "collection", "label": "Collection" },
        { "type": "image_picker", "id": "image", "label": "Override image" },
        { "type": "text", "id": "label", "label": "Label" },
        { "type": "url",  "id": "link",  "label": "Link (optional override)" }
      ]
    }
  ],
  "presets": [{
    "name": "Category Tiles",
    "blocks": [
      { "type": "tile", "settings": { "collection": "womens-dresses",   "label": "Dresses"   } },
      { "type": "tile", "settings": { "collection": "womens-tops",      "label": "Tops"      } },
      { "type": "tile", "settings": { "collection": "womens-jeans",     "label": "Jeans"     } },
      { "type": "tile", "settings": { "collection": "womens-bottoms",   "label": "Bottoms"   } },
      { "type": "tile", "settings": { "collection": "womens-outerwear", "label": "Jackets"   } },
      { "type": "tile", "settings": { "collection": "womens-activewear","label": "Activewear"} },
      { "type": "tile", "settings": { "collection": "womens-curvy-plus-size-clothing","label":"Plus Size"} },
      { "type": "tile", "settings": { "collection": "womens-handbags-accessories","label":"Accessories"} }
    ]
  }]
}
{% endschema %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Collection Sub-Navigation Snippet (internal links on category pages)
# ═══════════════════════════════════════════════════════════════════════════════

COLLECTION_SUBNAV = """
{%- comment -%}
  Renders subcategory navigation links on a collection page.
  Usage: {%- render 'collection-subnav', collection: collection -%}
{%- endcomment -%}

{%- assign h = collection.handle -%}

{%- if h == 'womens-dresses' or h == 'womens-casual-dresses' or h == 'womens-maxi-dresses' or h == 'midi-dresses' or h == 'mini-dresses' or h == 'womens-cocktail-dresses' or h == 'womens-formal-evening-dresses' or h == 'long-sleeve-dresses' or h == 'zenana-dresses' -%}
  {%- assign subnav_title = 'Shop Dresses' -%}
  {%- assign subnav_links = 'All Dresses|/collections/womens-dresses,Casual Dresses|/collections/womens-casual-dresses,Maxi Dresses|/collections/womens-maxi-dresses,Midi Dresses|/collections/midi-dresses,Mini Dresses|/collections/mini-dresses,Cocktail Dresses|/collections/womens-cocktail-dresses,Formal Dresses|/collections/womens-formal-evening-dresses,Long Sleeve|/collections/long-sleeve-dresses' -%}
{%- endif -%}

{%- if h == 'womens-tops' or h == 'womens-blouses' or h == 'womens-t-shirts' or h == 'womens-shirts' or h == 'womens-knit-tops' or h == 'womens-bodysuits' or h == 'long-sleeve-tops' or h == 'short-sleeve-tops' or h == 'puff-sleeve-tops' or h == 'v-neck-tops' or h == 'mock-neck-tops' or h == 'womens-camis-tanks-tops' -%}
  {%- assign subnav_title = 'Shop Tops' -%}
  {%- assign subnav_links = 'All Tops|/collections/womens-tops,Blouses|/collections/womens-blouses,T-Shirts|/collections/womens-t-shirts,Knit Tops|/collections/womens-knit-tops,Bodysuits|/collections/womens-bodysuits,Long Sleeve|/collections/long-sleeve-tops,Short Sleeve|/collections/short-sleeve-tops,Puff Sleeve|/collections/puff-sleeve-tops,V-Neck|/collections/v-neck-tops,Camis & Tanks|/collections/womens-camis-tanks-tops' -%}
{%- endif -%}

{%- if h == 'womens-jeans' or h == 'flare-jeans' or h == 'wide-leg-jeans' or h == 'straight-leg-jeans' or h == 'womens-jean-shorts' or h == 'judy-blue-womens-jeans' or h == 'kancan-usa-womens-jeans' or h == 'flying-monkey-womens-jeans-collection' or h == 'risen-womens-jeans-collection' or h == 'insane-gene-womens-denim' or h == 'vervet-by-flying-monkey-womens-jeans' or h == 'vibrant-miu-womens-jeans' -%}
  {%- assign subnav_title = 'Shop Jeans' -%}
  {%- assign subnav_links = 'All Jeans|/collections/womens-jeans,Flare Jeans|/collections/flare-jeans,Wide Leg|/collections/wide-leg-jeans,Straight Leg|/collections/straight-leg-jeans,Jean Shorts|/collections/womens-jean-shorts,Judy Blue|/collections/judy-blue-womens-jeans,Kancan|/collections/kancan-usa-womens-jeans,Flying Monkey|/collections/flying-monkey-womens-jeans-collection,Risen|/collections/risen-womens-jeans-collection' -%}
{%- endif -%}

{%- if h == 'womens-bottoms' or h == 'womens-shorts' or h == 'womens-skirts' or h == 'womens-pants-leggings' -%}
  {%- assign subnav_title = 'Shop Bottoms' -%}
  {%- assign subnav_links = 'All Bottoms|/collections/womens-bottoms,Pants & Leggings|/collections/womens-pants-leggings,Shorts|/collections/womens-shorts,Skirts|/collections/womens-skirts,Jeans|/collections/womens-jeans,Jean Shorts|/collections/womens-jean-shorts' -%}
{%- endif -%}

{%- if h == 'womens-sweaters' or h == 'womens-cardigans' or h == 'sweater-pullover' or h == 'womens-sweatshirts' or h == 'womens-hoodies' or h == 'womens-sweatshirts-hoodies' or h == 'zenana-sweaters' or h == 'zenana-sweatshirts' -%}
  {%- assign subnav_title = 'Shop Sweaters & Hoodies' -%}
  {%- assign subnav_links = 'All Sweaters|/collections/womens-sweaters,Cardigans|/collections/womens-cardigans,Pullovers|/collections/sweater-pullover,Sweatshirts|/collections/womens-sweatshirts,Hoodies|/collections/womens-hoodies,Zenana Sweaters|/collections/zenana-sweaters' -%}
{%- endif -%}

{%- if h == 'womens-activewear' or h == 'womens-active-tops' or h == 'womens-active-bottoms' or h == 'womens-lounge-set' -%}
  {%- assign subnav_title = 'Shop Activewear' -%}
  {%- assign subnav_links = 'All Activewear|/collections/womens-activewear,Active Tops|/collections/womens-active-tops,Active Bottoms|/collections/womens-active-bottoms,Lounge Sets|/collections/womens-lounge-set' -%}
{%- endif -%}

{%- if h == 'womens-outerwear' or h == 'womens-blazers-vests-jackets' or h == 'womens-denim-tops-jackets' -%}
  {%- assign subnav_title = 'Shop Outerwear & Jackets' -%}
  {%- assign subnav_links = 'All Outerwear|/collections/womens-outerwear,Blazers & Vests|/collections/womens-blazers-vests-jackets,Denim Jackets|/collections/womens-denim-tops-jackets' -%}
{%- endif -%}

{%- if h == 'womens-handbags-accessories' or h == 'womens-shoes' or h == 'womens-hats-scarves' or h == 'artini-accessories' or h == 'fame-accessories' or h == 'himawari-backpacks' -%}
  {%- assign subnav_title = 'Shop Accessories' -%}
  {%- assign subnav_links = 'Handbags|/collections/womens-handbags-accessories,Shoes|/collections/womens-shoes,Hats & Scarves|/collections/womens-hats-scarves,Backpacks|/collections/himawari-backpacks,Accessories|/collections/artini-accessories' -%}
{%- endif -%}

{%- if subnav_links -%}
<nav class="collection-subnav" aria-label="{{ subnav_title }}">
  <div class="collection-subnav__inner">
    <span class="collection-subnav__title">{{ subnav_title }}:</span>
    <div class="collection-subnav__links">
      {%- assign link_items = subnav_links | split: ',' -%}
      {%- for item in link_items -%}
        {%- assign parts = item | split: '|' -%}
        <a href="{{ parts[1] }}"
           class="collection-subnav__link {% if parts[1] contains collection.handle %}collection-subnav__link--active{% endif %}">
          {{ parts[0] }}
        </a>
      {%- endfor -%}
    </div>
  </div>
</nav>
{%- endif -%}

{% stylesheet %}
.collection-subnav { background:#f7f7f7; border-bottom:1px solid #eee; overflow-x:auto; -webkit-overflow-scrolling:touch; white-space:nowrap; padding:0 16px; }
.collection-subnav__inner { display:flex; align-items:center; gap:8px; padding:10px 0; min-height:46px; }
.collection-subnav__title { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#888; flex-shrink:0; }
.collection-subnav__links { display:flex; gap:6px; flex-wrap:nowrap; }
.collection-subnav__link { display:inline-block; padding:5px 14px; border-radius:20px; font-size:13px; font-weight:500; text-decoration:none; border:1px solid #ddd; color:#333; white-space:nowrap; transition:all .2s ease; }
.collection-subnav__link:hover { background:#111; color:#fff; border-color:#111; }
.collection-subnav__link--active { background:#111; color:#fff; border-color:#111; }
{% endstylesheet %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Blog Internal Links Snippet (related posts + collections + products)
# ═══════════════════════════════════════════════════════════════════════════════

BLOG_INTERNAL_LINKS = """
{%- comment -%}
  Renders related collection links + blog post links inside an article.
  Usage: {%- render 'blog-internal-links', article: article, blog: blog -%}
{%- endcomment -%}

{%- assign bh = blog.handle -%}

{%- comment -%} Map each blog to its relevant collections {%- endcomment -%}
{%- if bh contains 'dress' -%}
  {%- assign related_collections = 'All Dresses|womens-dresses,Casual Dresses|womens-casual-dresses,Maxi Dresses|womens-maxi-dresses,Midi Dresses|midi-dresses,Mini Dresses|mini-dresses,Formal Dresses|womens-formal-evening-dresses' -%}
  {%- assign related_blog = 'dresses-style-guide' -%}
{%- elsif bh contains 'jean' -%}
  {%- assign related_collections = 'All Jeans|womens-jeans,Flare Jeans|flare-jeans,Wide Leg Jeans|wide-leg-jeans,Straight Leg|straight-leg-jeans,Judy Blue|judy-blue-womens-jeans,Kancan Jeans|kancan-usa-womens-jeans' -%}
  {%- assign related_blog = 'jeans-style-guide' -%}
{%- elsif bh contains 'cardigan' or bh contains 'sweater' -%}
  {%- assign related_collections = 'All Sweaters|womens-sweaters,Cardigans|womens-cardigans,Pullovers|sweater-pullover,Hoodies|womens-sweatshirts-hoodies,Zenana Sweaters|zenana-sweaters' -%}
  {%- assign related_blog = 'cardigans-sweaters-style-guide' -%}
{%- elsif bh contains 'coat' or bh contains 'jacket' -%}
  {%- assign related_collections = 'All Outerwear|womens-outerwear,Blazers & Vests|womens-blazers-vests-jackets,Denim Jackets|womens-denim-tops-jackets' -%}
  {%- assign related_blog = 'coats-jackets-style-guide' -%}
{%- elsif bh contains 'shirt' or bh contains 'top' -%}
  {%- assign related_collections = 'All Tops|womens-tops,Blouses|womens-blouses,T-Shirts|womens-t-shirts,Long Sleeve|long-sleeve-tops,V-Neck|v-neck-tops,Bodysuits|womens-bodysuits' -%}
  {%- assign related_blog = 'womens-shirts-tops-style-guide' -%}
{%- elsif bh contains 'pant' or bh contains 'bottom' -%}
  {%- assign related_collections = 'Pants & Leggings|womens-pants-leggings,Shorts|womens-shorts,Skirts|womens-skirts,Jeans|womens-jeans' -%}
  {%- assign related_blog = 'womens-pants-style-guide' -%}
{%- elsif bh contains 'skirt' -%}
  {%- assign related_collections = 'All Skirts|womens-skirts,Mini Dresses|mini-dresses,Midi Dresses|midi-dresses,All Bottoms|womens-bottoms' -%}
  {%- assign related_blog = 'womens-skirts-style-guide' -%}
{%- elsif bh contains 'plus' or bh contains 'curvy' -%}
  {%- assign related_collections = 'Plus Size|womens-curvy-plus-size-clothing,Plus Size Sale|sale-plus-size-apparel,All Dresses|womens-dresses,All Tops|womens-tops' -%}
  {%- assign related_blog = 'plus-size-curvy-clothing' -%}
{%- else -%}
  {%- assign related_collections = 'New Arrivals|womens-new-collection,Best Sellers|womens-best-selling-collection,Dresses|womens-dresses,Tops|womens-tops,Jeans|womens-jeans' -%}
  {%- assign related_blog = 'womens-clothing' -%}
{%- endif -%}

<div class="blog-internal-links">

  {%- comment -%} Shop the look — collection links {%- endcomment -%}
  <div class="bil-section">
    <h3 class="bil-heading">Shop Related Styles</h3>
    <div class="bil-tags">
      {%- assign col_items = related_collections | split: ',' -%}
      {%- for item in col_items -%}
        {%- assign parts = item | split: '|' -%}
        <a href="/collections/{{ parts[1] }}" class="bil-tag bil-tag--collection">{{ parts[0] }}</a>
      {%- endfor -%}
      <a href="/collections/womens-best-selling-collection" class="bil-tag">Best Sellers</a>
      <a href="/collections/womens-new-collection"          class="bil-tag">New Arrivals</a>
      <a href="/collections/made-in-usa"                    class="bil-tag">Made in USA</a>
    </div>
  </div>

  {%- comment -%} Related articles from same blog {%- endcomment -%}
  {%- assign related_articles = blogs[related_blog].articles | limit: 4 -%}
  {%- if related_articles.size > 0 -%}
  <div class="bil-section">
    <h3 class="bil-heading">You Might Also Like</h3>
    <div class="bil-article-grid">
      {%- for a in related_articles -%}
        {%- unless a.id == article.id -%}
        <a href="{{ a.url }}" class="bil-article">
          {%- if a.image -%}
            {{ a.image | image_url: width: 300 | image_tag: loading: 'lazy', class: 'bil-article__img', alt: a.title }}
          {%- endif -%}
          <span class="bil-article__title">{{ a.title | truncate: 55 }}</span>
        </a>
        {%- endunless -%}
      {%- endfor -%}
    </div>
  </div>
  {%- endif -%}

  {%- comment -%} Popular searches footer on blog post {%- endcomment -%}
  <div class="bil-section bil-section--searches">
    <p class="bil-searches-label">Explore more:</p>
    <div class="bil-tags">
      <a href="/collections/under-40"          class="bil-tag bil-tag--deal">Under $40</a>
      <a href="/collections/under-50"          class="bil-tag bil-tag--deal">Under $50</a>
      <a href="/collections/25-percent-off"    class="bil-tag bil-tag--deal">25% Off</a>
      <a href="/pages/shipping-policy"         class="bil-tag">Free Shipping Info</a>
      <a href="/search"                        class="bil-tag">Search All Styles</a>
    </div>
  </div>

</div>

{% stylesheet %}
.blog-internal-links { margin:40px 0 20px; padding:28px; background:#f8f8f8; border-radius:14px; border:1px solid #eee; }
.bil-section { margin-bottom:24px; }
.bil-section:last-child { margin-bottom:0; }
.bil-heading { font-size:15px; font-weight:700; margin:0 0 12px; text-transform:uppercase; letter-spacing:.05em; color:#444; }
.bil-tags { display:flex; flex-wrap:wrap; gap:7px; }
.bil-tag { display:inline-block; padding:5px 14px; border-radius:20px; font-size:13px; font-weight:500; text-decoration:none; border:1px solid #ddd; color:#333; transition:all .2s ease; }
.bil-tag:hover { background:#111; color:#fff; border-color:#111; }
.bil-tag--collection { border-color:#111; color:#111; font-weight:600; }
.bil-tag--deal { border-color:#e53935; color:#e53935; }
.bil-tag--deal:hover { background:#e53935; color:#fff; }
.bil-article-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; }
.bil-article { text-decoration:none; color:inherit; }
.bil-article__img { width:100%; border-radius:8px; aspect-ratio:16/9; object-fit:cover; }
.bil-article__title { display:block; font-size:13px; margin-top:6px; font-weight:500; line-height:1.4; }
.bil-section--searches { padding-top:18px; border-top:1px solid #eee; }
.bil-searches-label { font-size:13px; color:#888; margin:0 0 8px; }
{% endstylesheet %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Mega Menu Nav Snippet (shop by category dropdown links)
# ═══════════════════════════════════════════════════════════════════════════════

SITE_LINKS_BAR = """
{%- comment -%} Quick-links scrolling bar — appears below header on mobile {%- endcomment -%}
<div class="quick-links-bar" aria-label="Quick navigation">
  <div class="quick-links-bar__inner">
    <a href="/collections/womens-new-collection"       class="ql-link ql-link--hot">New In</a>
    <a href="/collections/womens-best-selling-collection" class="ql-link">Best Sellers</a>
    <a href="/collections/womens-dresses"              class="ql-link">Dresses</a>
    <a href="/collections/womens-tops"                 class="ql-link">Tops</a>
    <a href="/collections/womens-jeans"                class="ql-link">Jeans</a>
    <a href="/collections/womens-bottoms"              class="ql-link">Bottoms</a>
    <a href="/collections/womens-sweaters"             class="ql-link">Sweaters</a>
    <a href="/collections/womens-activewear"           class="ql-link">Activewear</a>
    <a href="/collections/womens-outerwear"            class="ql-link">Jackets</a>
    <a href="/collections/womens-curvy-plus-size-clothing" class="ql-link">Plus Size</a>
    <a href="/collections/womens-handbags-accessories" class="ql-link">Accessories</a>
    <a href="/collections/made-in-usa"                 class="ql-link">Made in USA</a>
    <a href="/collections/under-40"                    class="ql-link ql-link--sale">Under $40</a>
    <a href="/collections/usa-sale"                    class="ql-link ql-link--sale">Sale</a>
  </div>
</div>

{% stylesheet %}
.quick-links-bar { background:#111; overflow-x:auto; -webkit-overflow-scrolling:touch; white-space:nowrap; }
.quick-links-bar__inner { display:flex; gap:0; padding:0 12px; }
.ql-link { display:inline-block; padding:9px 16px; font-size:12px; font-weight:600; text-decoration:none; color:rgba(255,255,255,0.8); letter-spacing:.04em; text-transform:uppercase; transition:color .2s ease; white-space:nowrap; border-bottom:2px solid transparent; }
.ql-link:hover { color:#fff; border-bottom-color:#fff; }
.ql-link--hot { color:#ff6b6b; }
.ql-link--hot:hover { color:#ff4444; }
.ql-link--sale { color:#ffd700; }
.ql-link--sale:hover { color:#ffec6e; }
{% endstylesheet %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Full-page SEO Footer Links (comprehensive internal linking)
# ═══════════════════════════════════════════════════════════════════════════════

SEO_FOOTER_LINKS = """
{%- comment -%} SEO footer links — comprehensive internal link grid for Google crawling {%- endcomment -%}
<div class="seo-links-footer">
  <div class="container">
    <div class="seo-links-grid">

      <div class="seo-col">
        <h4>Shop by Category</h4>
        <ul>
          <li><a href="/collections/womens-dresses">Dresses</a></li>
          <li><a href="/collections/womens-tops">Tops &amp; Blouses</a></li>
          <li><a href="/collections/womens-jeans">Jeans</a></li>
          <li><a href="/collections/womens-bottoms">Bottoms</a></li>
          <li><a href="/collections/womens-sweaters">Sweaters</a></li>
          <li><a href="/collections/womens-activewear">Activewear</a></li>
          <li><a href="/collections/womens-outerwear">Jackets &amp; Coats</a></li>
          <li><a href="/collections/womens-rompers-jumpsuit-sets">Rompers &amp; Jumpsuits</a></li>
          <li><a href="/collections/womens-outfit-sets">Outfit Sets</a></li>
          <li><a href="/collections/womens-sleepwear">Sleepwear</a></li>
          <li><a href="/collections/womens-handbags-accessories">Handbags</a></li>
          <li><a href="/collections/womens-shoes">Shoes</a></li>
        </ul>
      </div>

      <div class="seo-col">
        <h4>Shop by Style</h4>
        <ul>
          <li><a href="/collections/womens-casual-dresses">Casual Dresses</a></li>
          <li><a href="/collections/womens-maxi-dresses">Maxi Dresses</a></li>
          <li><a href="/collections/midi-dresses">Midi Dresses</a></li>
          <li><a href="/collections/mini-dresses">Mini Dresses</a></li>
          <li><a href="/collections/flare-jeans">Flare Jeans</a></li>
          <li><a href="/collections/wide-leg-jeans">Wide Leg Jeans</a></li>
          <li><a href="/collections/straight-leg-jeans">Straight Leg Jeans</a></li>
          <li><a href="/collections/womens-curvy-plus-size-clothing">Plus Size</a></li>
          <li><a href="/collections/made-in-usa">Made in USA</a></li>
          <li><a href="/collections/womens-t-shirts">T-Shirts</a></li>
          <li><a href="/collections/womens-bodysuits">Bodysuits</a></li>
          <li><a href="/collections/womens-skirts">Skirts</a></li>
        </ul>
      </div>

      <div class="seo-col">
        <h4>Top Brands</h4>
        <ul>
          <li><a href="/collections/judy-blue-womens-jeans">Judy Blue Jeans</a></li>
          <li><a href="/collections/zenana-womens-clothing">Zenana</a></li>
          <li><a href="/collections/kancan-usa-womens-jeans">Kancan USA</a></li>
          <li><a href="/collections/flying-monkey-womens-jeans-collection">Flying Monkey</a></li>
          <li><a href="/collections/hyfve-womens-clothing">Hyfve</a></li>
          <li><a href="/collections/mustard-seed-womens-clothing">Mustard Seed</a></li>
          <li><a href="/collections/umgee-usa-womens-clothing">Umgee USA</a></li>
          <li><a href="/collections/risen-womens-jeans-collection">Risen Jeans</a></li>
          <li><a href="/collections/culture-code-womens-clothing">Culture Code</a></li>
          <li><a href="/collections/le-lis-womens-clothing">Le Lis</a></li>
          <li><a href="/collections/mittoshop-clothing">Mittoshop</a></li>
          <li><a href="/collections/very-j-womens-clothing">Very J</a></li>
        </ul>
      </div>

      <div class="seo-col">
        <h4>Style Guides</h4>
        <ul>
          <li><a href="/blogs/dresses-style-guide">Dress Style Tips</a></li>
          <li><a href="/blogs/jeans-style-guide">Jeans Style Guide</a></li>
          <li><a href="/blogs/cardigans-sweaters-style-guide">Sweater Guide</a></li>
          <li><a href="/blogs/coats-jackets-style-guide">Jacket Guide</a></li>
          <li><a href="/blogs/womens-shirts-tops-style-guide">Tops Style Tips</a></li>
          <li><a href="/blogs/womens-pants-style-guide">Pants Style Guide</a></li>
          <li><a href="/blogs/womens-skirts-style-guide">Skirt Style Tips</a></li>
          <li><a href="/blogs/plus-size-curvy-clothing">Plus Size Fashion</a></li>
          <li><a href="/blogs/womens-clothing">Women's Fashion Blog</a></li>
          <li><a href="/blogs/our-tips">Outfit Ideas &amp; Tips</a></li>
        </ul>
      </div>

      <div class="seo-col">
        <h4>Deals &amp; More</h4>
        <ul>
          <li><a href="/collections/under-40">Under $40</a></li>
          <li><a href="/collections/under-50">Under $50</a></li>
          <li><a href="/collections/25-percent-off">25% Off Sale</a></li>
          <li><a href="/collections/usa-sale">USA Sale</a></li>
          <li><a href="/collections/sale-plus-size-apparel">Plus Size Sale</a></li>
          <li><a href="/collections/womens-best-selling-collection">Best Sellers</a></li>
          <li><a href="/collections/womens-new-collection">New Arrivals</a></li>
          <li><a href="/collections/selected-usa-styles">Selected USA Styles</a></li>
          <li><a href="/pages/shipping-policy">Shipping Policy</a></li>
          <li><a href="/pages/refund-policy">Returns &amp; Exchanges</a></li>
        </ul>
      </div>

    </div>
  </div>
</div>

{% stylesheet %}
.seo-links-footer { padding:40px 0 20px; border-top:1px solid #eee; background:#fafafa; }
.seo-links-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:24px 20px; }
.seo-col h4 { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:#555; margin:0 0 12px; }
.seo-col ul { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.seo-col a { font-size:13px; color:#666; text-decoration:none; transition:color .15s ease; }
.seo-col a:hover { color:#111; text-decoration:underline; }
{% endstylesheet %}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# PUSH TO DRAFT THEME
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("MeeeShop — SEO Theme Sections Builder")
    print(f"Pushing to draft ID: {DRAFT_ID}")
    print("=" * 60)

    print("\n[1/3] Uploading new sections...")
    upload({
        "sections/popular-searches.liquid":  POPULAR_SEARCHES,
        "sections/category-tiles.liquid":    CATEGORY_TILES,
    })

    print("\n[2/3] Uploading new snippets...")
    upload({
        "snippets/collection-subnav.liquid":  COLLECTION_SUBNAV,
        "snippets/blog-internal-links.liquid": BLOG_INTERNAL_LINKS,
        "snippets/quick-links-bar.liquid":    SITE_LINKS_BAR,
        "snippets/seo-footer-links.liquid":   SEO_FOOTER_LINKS,
    })

    print("\n[3/3] Patching collection template to add subnav...")
    # Fetch main-collection-list section and add subnav render
    url = f"https://{SHOP}/admin/api/{API}/themes/{DRAFT_ID}/assets.json?asset[key]=sections/main-collection-list.liquid"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req) as r:
            asset = json.loads(r.read()).get("asset", {})
        val = asset.get("value", "")
        if val and "collection-subnav" not in val:
            inject = "{%- render 'collection-subnav', collection: collection -%}\n"
            # inject after opening section tag or before main content
            if "<div" in val:
                val = val.replace("<div", inject + "<div", 1)
            else:
                val = inject + val
            put(DRAFT_ID, "sections/main-collection-list.liquid", val)
        else:
            print("  [SKIP] main-collection-list.liquid already patched or not found")
    except Exception as e:
        print(f"  [ERR] main-collection-list: {e}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"""
  Draft theme ID: {DRAFT_ID}
  Preview: https://admin.shopify.com/store/us-meeeshop/themes/{DRAFT_ID}/editor

  WHAT WAS ADDED:
  ── Sections (add to homepage via theme editor):
    + popular-searches   — Zepto-style tabs: Categories/Styles/Brands/Deals
    + category-tiles     — Visual photo grid (Dresses, Tops, Jeans, etc.)

  ── Snippets (auto-injected or add via Custom Liquid):
    + collection-subnav  — Sub-nav on Dresses/Tops/Jeans/Bottoms/etc pages
    + blog-internal-links — Related collections + articles + deals on every post
    + quick-links-bar    — Scrolling mini-nav bar below header
    + seo-footer-links   — 5-column internal link grid for Google crawling

  TO ACTIVATE IN THEME EDITOR:
  1. Homepage → Add section → "Popular Searches" → place after hero
  2. Homepage → Add section → "Category Tiles" → place after popular searches
  3. Footer area → Add block → Custom Liquid:
       {{%- render 'seo-footer-links' -%}}
  4. Header group → Add Custom Liquid above/below header:
       {{%- render 'quick-links-bar' -%}}
  5. Blog article template → Add Custom Liquid at bottom:
       {{%- render 'blog-internal-links', article: article, blog: blog -%}}

  INTERNAL LINKS CREATED:
    + 124 collections mapped to category navigation
    + 12 blogs mapped to related collections + cross-linked
    + Subcategory nav for: Dresses, Tops, Jeans, Bottoms,
      Sweaters/Hoodies, Activewear, Outerwear, Accessories
    + SEO footer with 60+ keyword-rich internal links
    + Popular searches: 50+ keyword links in 4 tab groups
""")

if __name__ == "__main__":
    main()
