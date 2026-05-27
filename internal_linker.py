#!/usr/bin/env python3
"""
internal_linker.py — Automated internal linking for MeeeShop blog posts & pages
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Builds a keyword→URL map from all blog posts, products, and collections.
Scans articles for unlinked keyword mentions and injects links.

Modes:
  --weekly  : Link articles created in last 7 days (default on schedule)
  --force   : Link ALL articles in store (batch mode available)
  --dry-run : Print suggestions without modifying Shopify (default mode)

Usage:
  python internal_linker.py --weekly --dry-run     # Suggest links for new articles
  python internal_linker.py --force --apply        # Auto-link all articles
  python internal_linker.py --weekly --apply       # Auto-link recent articles

  # Force mode with batching (for GitHub Actions):
  python internal_linker.py --force --apply --batch-size 50 --batch-index 0
"""

import os, sys, re, json, time, argparse, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Set
from urllib.parse import urlencode
import requests
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

STORE  = get_secret("SHOPIFY_STORE")
TOKEN  = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS  = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE   = f"https://{STORE}/admin/api/2024-01"
SITE   = "https://us.meeeshop.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"internal_linker_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HTML PARSING & LINK DETECTION
# ══════════════════════════════════════════════════════════════════════════════

class LinkExtractor(HTMLParser):
    """Extract all href targets from HTML to avoid re-linking existing links."""

    def __init__(self):
        super().__init__()
        self.links = set()
        self.in_link = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.in_link = True
            for attr, value in attrs:
                if attr == "href" and value:
                    self.links.add(value.lower().strip())

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_link = False


def extract_existing_links(html: str) -> Set[str]:
    """Parse HTML and return set of all href targets."""
    if not html:
        return set()
    try:
        parser = LinkExtractor()
        parser.feed(html)
        return parser.links
    except Exception as e:
        logger.warning(f"Failed to parse HTML links: {e}")
        return set()


def strip_html(html: str) -> str:
    """Remove HTML tags, keep text."""
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def text_within_tag(html: str, tag: str = "p") -> str:
    """Extract text from specific HTML tag."""
    pattern = f"<{tag}[^>]*>([^<]*)</{tag}>"
    matches = re.findall(pattern, html, re.IGNORECASE)
    return " ".join(matches)


# ══════════════════════════════════════════════════════════════════════════════
# KEYWORD EXTRACTION & NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "his", "how", "i", "if", "in", "is",
    "it", "its", "just", "of", "on", "or", "she", "that", "the", "to", "too",
    "was", "what", "when", "where", "which", "who", "will", "with", "you",
    "your", "not", "no", "we", "them", "their", "there", "then", "about",
    "more", "some", "such", "than", "them", "then", "now", "out", "up", "so",
    "can", "do", "does", "did", "get", "got", "make", "made", "new", "only",
    "this", "that", "these", "those", "my", "your", "his", "her", "its",
    "our", "their", "all", "each", "every", "either", "neither", "many",
    "few", "several", "most", "least", "best", "worst", "better", "worse",
    "good", "bad", "great", "small", "large", "big", "little", "old", "young",
    "high", "low", "bold", "bright", "dark", "light", "colors", "style",
    "look", "wear", "day", "way", "time", "year", "say", "go", "come", "take"
}

# High-value keywords: ONLY product types & materials (women's fashion)
# These are words women shoppers actually search for when looking to buy
HIGH_VALUE_KEYWORDS = {
    # Garment types
    "dress", "dresses", "top", "tops", "blouse", "shirt", "jean", "jeans",
    "pant", "pants", "skirt", "skirts", "jacket", "coat", "sweater", "cardigan",
    "blazer", "hoodie", "shorts", "leggings", "romper", "jumpsuit", "bodysuit",
    "vest", "tank", "cami", "tunic", "tee", "crop", "maxi", "midi",
    # Materials & fabrics
    "leather", "denim", "cotton", "silk", "linen", "lace", "mesh", "satin", "velvet",
    # Patterns & colors (only when paired with garment type — see _register_keywords)
    "floral", "striped", "stripe", "solid", "print",
    # Handbags & accessories
    "handbag", "bag", "purse", "tote", "crossbody", "backpack", "clutch", "wallet",
}


def normalize_keyword(kw: str) -> str:
    """Normalize keyword for matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9\s-]", "", kw.lower()).strip()


def extract_high_value_keywords(text: str) -> Set[str]:
    """Extract high-value keywords: prefer 2-word pairs over single words."""
    if not text:
        return set()

    text_lower = strip_html(text).lower()
    words = re.findall(r"\b[a-z]+(?:-[a-z]+)?\b", text_lower)
    found = set()

    # Look for 2-word phrases first (garment + style/material/color)
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        # Check if phrase contains at least one high-value keyword
        has_high_value = any(kw in phrase for kw in HIGH_VALUE_KEYWORDS)
        if has_high_value and phrase not in STOP_WORDS:
            found.add(phrase)

    # Fall back to single high-value keywords only if no pairs found
    for keyword in HIGH_VALUE_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text_lower):
            found.add(keyword)

    return found


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _req(method: str, url: str, **kw) -> requests.Response:
    """HTTP request with retry logic."""
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADS, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                logger.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")


def fetch_all_blogs() -> List[Dict]:
    """Fetch all blogs."""
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])


def fetch_articles(blog_id: int, days_since: int = None) -> List[Dict]:
    """Fetch articles from a blog, optionally filtered by creation date."""
    articles = []
    params = {"limit": 250}

    url = f"{BASE}/blogs/{blog_id}/articles.json"
    while url:
        r = _req("get", url, params=params)
        r.raise_for_status()
        data = r.json()

        for article in data.get("articles", []):
            if days_since:
                created = datetime.fromisoformat(article["created_at"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - created).days
                if age > days_since:
                    continue
            articles.append(article)

        # Pagination
        url = None
        link_header = r.headers.get("Link", "")
        if 'rel="next"' in link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                url = match.group(1)
                params = {}

    return articles


def fetch_all_products() -> List[Dict]:
    """Fetch all active products."""
    products = []
    params = {"limit": 250, "status": "active"}

    url = f"{BASE}/products.json"
    while url:
        r = _req("get", url, params=params)
        r.raise_for_status()
        data = r.json()
        products.extend(data.get("products", []))

        url = None
        link_header = r.headers.get("Link", "")
        if 'rel="next"' in link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                url = match.group(1)
                params = {}

    return products


def fetch_all_collections() -> List[Dict]:
    """Fetch all collections."""
    r = _req("get", f"{BASE}/custom_collections.json", params={"limit": 250})
    r.raise_for_status()
    return r.json().get("custom_collections", [])


def update_article(blog_id: int, article_id: int, body_html: str) -> bool:
    """Update article body HTML via API."""
    try:
        r = _req("put", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json",
                 json={"article": {"body_html": body_html}})
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to update article {article_id}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# KEYWORD → URL MAPPING
# ══════════════════════════════════════════════════════════════════════════════

class LinkMap:
    """Maps keywords to linkable URLs."""

    def __init__(self):
        self.keyword_to_urls: Dict[str, List[Tuple[str, str]]] = {}  # keyword -> [(url, anchor_text)]

    def add_product(self, title: str, handle: str):
        """Register product keywords."""
        url = f"{SITE}/products/{handle}"
        self._register_keywords(title, url, title)

    def add_collection(self, title: str, handle: str):
        """Register collection keywords."""
        url = f"{SITE}/collections/{handle}"
        self._register_keywords(title, url, title)

    def add_article(self, title: str, blog_handle: str, article_handle: str):
        """Register article keywords."""
        url = f"{SITE}/blogs/{blog_handle}/{article_handle}"
        self._register_keywords(title, url, title)

    def _register_keywords(self, text: str, url: str, anchor_text: str):
        """Extract ONLY high-value keywords and map to URL."""
        keywords = extract_high_value_keywords(text)
        for kw in keywords:
            normalized = normalize_keyword(kw)
            if normalized and len(normalized) > 2:
                if normalized not in self.keyword_to_urls:
                    self.keyword_to_urls[normalized] = []
                # Avoid duplicates
                if (url, anchor_text) not in self.keyword_to_urls[normalized]:
                    self.keyword_to_urls[normalized].append((url, anchor_text))

    def find_link_for_keyword(self, keyword: str) -> Tuple[str, str]:
        """Find best URL + anchor text for keyword. Returns (url, anchor_text) or (None, None)."""
        normalized = normalize_keyword(keyword)
        if normalized in self.keyword_to_urls and self.keyword_to_urls[normalized]:
            url, anchor = self.keyword_to_urls[normalized][0]  # First match
            return url, anchor
        return None, None


# ══════════════════════════════════════════════════════════════════════════════
# LINK INJECTION & SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def find_unlinked_keywords(article_text: str, existing_links: Set[str], link_map: LinkMap) -> List[Dict]:
    """
    Scan article for keywords that appear in link_map but are not yet linked.
    Returns list of {keyword, url, anchor_text, count}.
    """
    suggestions = []
    article_lower = article_text.lower()

    for keyword, url_list in link_map.keyword_to_urls.items():
        if not url_list:
            continue

        url, anchor_text = url_list[0]

        # Skip if already linked
        if url.lower() in existing_links:
            continue

        # Count occurrences in article text (case-insensitive, word boundary)
        pattern = r"\b" + re.escape(keyword) + r"\b"
        matches = list(re.finditer(pattern, article_lower))

        if matches:
            suggestions.append({
                "keyword": keyword,
                "url": url,
                "anchor_text": anchor_text,
                "count": len(matches),
                "first_position": matches[0].start()
            })

    # Sort by position (link first occurrence first)
    return sorted(suggestions, key=lambda x: x["first_position"])


def inject_link_into_html(html: str, keyword: str, url: str, anchor_text: str) -> Tuple[str, bool]:
    """
    Inject an <a> tag for the first unlinked occurrence of keyword in HTML.
    Avoids linking text that's already inside an <a> tag.
    Returns (modified_html, was_link_injected).
    """
    existing_links = extract_existing_links(html)
    if url.lower() in existing_links:
        return html, False

    # Build regex to find the keyword outside of HTML tags
    pattern = r"(?<![a-z>])\b" + re.escape(keyword) + r"\b(?![a-z<])"

    replaced = [False]
    def replace_first(match):
        if not replaced[0]:
            replaced[0] = True
            return f'<a href="{url}">{match.group(0)}</a>'
        return match.group(0)

    # Replace only first occurrence
    result = re.sub(pattern, replace_first, html, count=1, flags=re.IGNORECASE)
    return result, replaced[0]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def build_link_map() -> LinkMap:
    """Build keyword → URL map from all products, collections, and articles."""
    logger.info("Building link map...")
    link_map = LinkMap()

    # Add products
    logger.info("  Fetching products...")
    products = fetch_all_products()
    for product in products:
        title = product.get("title", "")
        handle = product.get("handle", "")
        if title and handle:
            link_map.add_product(title, handle)
            # Also add tags as keywords
            for tag in product.get("tags", "").split(","):
                tag = tag.strip()
                if tag and len(tag) > 2:
                    link_map.add_product(tag, handle)
    logger.info(f"    Added {len(products)} products")

    # Add collections
    logger.info("  Fetching collections...")
    collections = fetch_all_collections()
    for collection in collections:
        title = collection.get("title", "")
        handle = collection.get("handle", "")
        if title and handle:
            link_map.add_collection(title, handle)
    logger.info(f"    Added {len(collections)} collections")

    # Add articles (to enable cross-article linking)
    logger.info("  Fetching articles...")
    blogs = fetch_all_blogs()
    article_count = 0
    for blog in blogs:
        articles = fetch_articles(blog["id"])
        for article in articles:
            title = article.get("title", "")
            blog_handle = blog.get("handle", "")
            article_handle = article.get("handle", "")
            if title and blog_handle and article_handle:
                link_map.add_article(title, blog_handle, article_handle)
                article_count += 1
    logger.info(f"    Added {article_count} articles")

    logger.info(f"Link map built: {len(link_map.keyword_to_urls)} unique keywords")
    return link_map


def process_articles(mode: str, apply: bool, batch_size: int = None, batch_index: int = None, max_links_per_article: int = 3):
    """Process articles and inject links (max 2-3 per article)."""
    logger.info(f"Processing articles in {mode} mode (apply={apply}, max {max_links_per_article} links/article)...")

    link_map = build_link_map()

    blogs = fetch_all_blogs()
    total_articles = 0
    total_links_injected = 0
    total_links_suggested = 0
    detailed_log = []  # Store detailed info for report

    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog.get("handle", "")
        blog_title = blog.get("title", "")

        # Fetch articles
        if mode == "weekly":
            articles = fetch_articles(blog_id, days_since=7)
            logger.info(f"Blog '{blog_title}': {len(articles)} articles from last 7 days")
        else:  # force
            articles = fetch_articles(blog_id, days_since=None)
            logger.info(f"Blog '{blog_title}': {len(articles)} total articles")

        # Apply batching if requested
        if batch_size and batch_index is not None:
            start = batch_index * batch_size
            end = start + batch_size
            articles = articles[start:end]
            logger.info(f"  Batch {batch_index}: processing articles {start}-{end-1}")

        for article in articles:
            total_articles += 1
            article_id = article["id"]
            article_handle = article.get("handle", "")
            article_title = article.get("title", "")
            body_html = article.get("body_html", "")
            article_url = f"{SITE}/blogs/{blog_handle}/{article_handle}"

            if not body_html:
                continue

            # Find existing links to avoid re-linking
            existing_links = extract_existing_links(body_html)

            # Find unlinked keywords
            suggestions = find_unlinked_keywords(body_html, existing_links, link_map)

            if suggestions:
                article_log = {
                    "article_title": article_title,
                    "article_url": article_url,
                    "blog_name": blog_title,
                    "links_injected": [],
                    "links_skipped": []
                }

                logger.info(f"Article '{article_title}': {len(suggestions)} link suggestions (limiting to {max_links_per_article})")
                total_links_suggested += len(suggestions)

                # Inject links (with per-article limit)
                modified_html = body_html
                injected_count = 0

                for suggestion in suggestions:
                    # HARD LIMIT: stop after max_links_per_article injected
                    if injected_count >= max_links_per_article:
                        link_info = {
                            "keyword": suggestion["keyword"],
                            "reason": f"Limit reached ({max_links_per_article} max per article)"
                        }
                        article_log["links_skipped"].append(link_info)
                        continue

                    keyword = suggestion["keyword"]
                    url = suggestion["url"]
                    anchor_text = suggestion["anchor_text"]
                    mention_count = suggestion["count"]

                    new_html, was_injected = inject_link_into_html(modified_html, keyword, url, anchor_text)

                    if was_injected:
                        modified_html = new_html
                        injected_count += 1
                        link_info = {
                            "keyword": keyword,
                            "target_url": url,
                            "anchor_text": anchor_text,
                            "occurrences_in_article": mention_count
                        }
                        article_log["links_injected"].append(link_info)
                        logger.info(f"  ✓ Linked '{keyword}' ({mention_count} mentions) → {url}")
                    else:
                        link_info = {
                            "keyword": keyword,
                            "reason": "Already linked or regex match failed"
                        }
                        article_log["links_skipped"].append(link_info)
                        logger.debug(f"  ⊘ Skipped '{keyword}' (already linked)")

                if injected_count > 0:
                    total_links_injected += injected_count
                    detailed_log.append(article_log)

                    if apply:
                        if update_article(blog_id, article_id, modified_html):
                            logger.info(f"  ✓ Updated article with {injected_count} links")
                        else:
                            logger.error(f"  ✗ Failed to update article")
                    else:
                        logger.info(f"  [DRY RUN] Would inject {injected_count} links")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info(f"SUMMARY:")
    logger.info(f"  Total articles processed: {total_articles}")
    logger.info(f"  Total link suggestions found: {total_links_suggested}")
    logger.info(f"  Total links injected: {total_links_injected}")
    logger.info(f"  Max links per article: {max_links_per_article}")
    logger.info(f"  Mode: {mode} | Apply: {apply}")
    logger.info("=" * 80)

    return {
        "articles_processed": total_articles,
        "suggestions": total_links_suggested,
        "links_injected": total_links_injected,
        "mode": mode,
        "apply": apply,
        "max_links_per_article": max_links_per_article,
        "timestamp": datetime.now().isoformat(),
        "detailed_log": detailed_log
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Internal linking automation for MeeeShop blog")
    parser.add_argument("--weekly", action="store_true", help="Process articles from last 7 days")
    parser.add_argument("--force", action="store_true", help="Process all articles in store")
    parser.add_argument("--apply", action="store_true", help="Apply changes to Shopify (default: dry-run)")
    parser.add_argument("--batch-size", type=int, help="Batch size for force mode")
    parser.add_argument("--batch-index", type=int, help="Batch index for force mode")
    parser.add_argument("--max-links", type=int, default=3, help="Max internal links per article (default: 3)")

    args = parser.parse_args()

    # Default to weekly
    mode = "force" if args.force else "weekly"

    result = process_articles(
        mode=mode,
        apply=args.apply,
        batch_size=args.batch_size,
        batch_index=args.batch_index,
        max_links_per_article=args.max_links
    )

    # Save report
    report_file = f"internal_linker_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Report saved to {report_file}")


if __name__ == "__main__":
    main()
