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

import os, sys, re, json, time, argparse, logging, html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Set
from urllib.parse import urlencode
import requests
from html.parser import HTMLParser

# Ensure stdout/stderr use UTF-8 on Windows to avoid UnicodeEncodeErrors
if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
from ai_client import generate

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
        logging.FileHandler(f"internal_linker_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
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
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "s",
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

# High-value keywords: ~45 core fashion terms (garment types & materials only)
# These are words women shoppers actually search for when looking to buy
HIGH_VALUE_KEYWORDS = {
    # Garment types (primary linking targets)
    "dress", "dresses", "top", "tops", "blouse", "shirt", "jean", "jeans",
    "pant", "pants", "skirt", "skirts", "jacket", "coat", "sweater", "cardigan",
    "blazer", "hoodie", "shorts", "leggings", "romper", "jumpsuit",
    "tank", "tunic", "tee", "crop", "maxi", "midi",
    # Materials & fabrics (high-value when paired with garment types)
    "leather", "denim", "cotton", "silk", "linen", "lace", "mesh", "satin", "velvet",
    # Accessories (handbags & bags only)
    "handbag", "bag", "purse", "tote", "crossbody", "backpack", "clutch",
}

# Contextual modifiers: words that pair with garment types for higher relevance scoring
CONTEXTUAL_MODIFIERS = {
    # Materials
    "leather", "denim", "cotton", "silk", "linen", "lace", "mesh", "satin", "velvet",
    # Patterns
    "floral", "striped", "stripe", "solid", "print", "polka", "checkered",
    # Colors (curated list of common fashion colors)
    "black", "white", "red", "blue", "green", "yellow", "pink", "gray", "grey",
    "navy", "cream", "beige", "brown", "purple", "orange",
}


# ZSV Brand and Product Type Keywords (Targeted search terms)
HIGH_PRIORITY_KEYWORDS = {
    # Brands
    "zenana", "pol", "emory park", "judy blue", "risen", "risen jeans",
    "umgee usa", "umgee", "hyfve", "bibi", "artemis vintage",
    # Specific ZSV Product Types
    "straight leg jeans", "flare jeans", "wide leg jeans", "mini dresses",
    "midi dresses", "puff sleeve tops", "long sleeve tops", "short sleeve tops",
    "cowl neck maxi dress", "denim tops", "denim jackets", "knit tops",
    "casual dresses", "maxi dresses", "cocktail dresses", "t-shirts",
    "sweatshirts", "hoodies", "cardigans", "rompers", "jumpsuits",
    "handbags", "plus size", "curvy", "made in usa", "fall clothing"
}


def normalize_keyword(kw: str) -> str:
    """Normalize keyword for matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9\s-]", "", kw.lower()).strip()


def extract_high_value_keywords(text: str) -> List[Tuple[str, float]]:
    """Extract high-value keywords with relevance scores: prefer 2-word pairs over singles.
    Returns sorted list of (keyword, score) tuples, highest relevance first."""
    if not text:
        return []

    text_lower = strip_html(text).lower()
    words = re.findall(r"\b[a-z]+(?:-[a-z]+)?\b", text_lower)
    scored_keywords = {}  # keyword -> max_score

    # Priority 0: Exact ZSV Brand / Product Type keywords (highest priority)
    for keyword in HIGH_PRIORITY_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text_lower):
            scored_keywords[keyword] = 1.0

    # Priority 1: 2-word contextual pairs (garment + modifier)
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        word1, word2 = words[i], words[i+1]

        # Check for garment+modifier or modifier+garment patterns
        if word1 in HIGH_VALUE_KEYWORDS and word2 in CONTEXTUAL_MODIFIERS:
            if phrase not in STOP_WORDS and phrase not in scored_keywords:
                scored_keywords[phrase] = 0.9  # Highest priority: garment+modifier
        elif word2 in HIGH_VALUE_KEYWORDS and word1 in CONTEXTUAL_MODIFIERS:
            if phrase not in STOP_WORDS and phrase not in scored_keywords:
                scored_keywords[phrase] = 0.9  # Highest priority: modifier+garment

    # Priority 2: Any 2-word phrase with a high-value keyword (less selective)
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        word1, word2 = words[i], words[i+1]
        if len(word1) <= 1 or len(word2) <= 1 or word1 in STOP_WORDS or word2 in STOP_WORDS:
            continue
        if any(kw in phrase.split() for kw in HIGH_VALUE_KEYWORDS):
            if phrase not in STOP_WORDS and phrase not in scored_keywords:
                scored_keywords[phrase] = 0.7

    # Priority 3: Single high-value keywords (lowest priority)
    for keyword in HIGH_VALUE_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text_lower):
            if keyword not in scored_keywords:
                scored_keywords[keyword] = 0.5

    # Return sorted by score (highest first)
    return sorted(scored_keywords.items(), key=lambda x: x[1], reverse=True)


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
    """Fetch all collections (both custom and smart)."""
    collections = []
    
    # 1. Custom collections
    try:
        r = _req("get", f"{BASE}/custom_collections.json", params={"limit": 250})
        r.raise_for_status()
        collections.extend(r.json().get("custom_collections", []))
    except Exception as e:
        logger.error(f"Failed to fetch custom collections: {e}")

    # 2. Smart collections
    try:
        r = _req("get", f"{BASE}/smart_collections.json", params={"limit": 250})
        r.raise_for_status()
        collections.extend(r.json().get("smart_collections", []))
    except Exception as e:
        logger.error(f"Failed to fetch smart collections: {e}")

    return collections


def fetch_products_for_collection(collection_id: int) -> List[Dict]:
    """Fetch active, in-stock products belonging to a collection."""
    if collection_id in COLLECTION_ID_TO_PRODUCTS:
        return COLLECTION_ID_TO_PRODUCTS[collection_id]

    url = f"{BASE}/products.json"
    try:
        # Fetch up to 25 products to filter for in-stock ones
        r = _req("get", url, params={"collection_id": collection_id, "limit": 25, "status": "active"})
        r.raise_for_status()
        all_prods = r.json().get("products", [])

        in_stock_prods = []
        for p in all_prods:
            # Check if active
            if p.get("status") and p.get("status") != "active":
                continue
            # Check if in stock
            variants = p.get("variants", [])
            is_in_stock = False
            for v in variants:
                qty = v.get("inventory_quantity", 0)
                policy = v.get("inventory_policy", "deny")
                mgmt = v.get("inventory_management")
                if mgmt is None or qty > 0 or policy == "continue":
                    is_in_stock = True
                    break
            if is_in_stock:
                in_stock_prods.append(p)
                if len(in_stock_prods) >= 4:
                    break

        COLLECTION_ID_TO_PRODUCTS[collection_id] = in_stock_prods
        return in_stock_prods
    except Exception as e:
        logger.error(f"Failed to fetch products for collection {collection_id}: {e}")
        return []


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
        self.keyword_to_urls: Dict[str, List[Tuple[str, str, bool]]] = {}  # keyword -> [(url, anchor_text, is_collection)]

    def add_product(self, title: str, handle: str):
        """Register product keywords."""
        url = f"{SITE}/products/{handle}"
        self._register_keywords(title, url, title, is_collection=False)

    def add_collection(self, title: str, handle: str):
        """Register collection keywords."""
        url = f"{SITE}/collections/{handle}"
        self._register_keywords(title, url, title, is_collection=True)

    def add_article(self, title: str, blog_handle: str, article_handle: str):
        """Register article keywords."""
        url = f"{SITE}/blogs/{blog_handle}/{article_handle}"
        self._register_keywords(title, url, title, is_collection=False)

    def _register_keywords(self, text: str, url: str, anchor_text: str, is_collection: bool):
        """Extract ONLY high-value keywords and map to URL."""
        keywords_scored = extract_high_value_keywords(text)
        for kw, score in keywords_scored:  # Now returns (keyword, score) tuples
            normalized = normalize_keyword(kw)
            if normalized and len(normalized) > 2:
                if normalized not in self.keyword_to_urls:
                    self.keyword_to_urls[normalized] = []
                # Avoid duplicates
                if not any(item[0] == url for item in self.keyword_to_urls[normalized]):
                    self.keyword_to_urls[normalized].append((url, anchor_text, is_collection))

    def find_link_for_keyword(self, keyword: str, article_context: str = None) -> Tuple[str, str]:
        """Find best URL + anchor text for keyword. Returns (url, anchor_text) or (None, None)."""
        normalized = normalize_keyword(keyword)
        if normalized in self.keyword_to_urls and self.keyword_to_urls[normalized]:
            # Prioritize collections over other matches
            collections = [m for m in self.keyword_to_urls[normalized] if m[2]]
            products_or_articles = [m for m in self.keyword_to_urls[normalized] if not m[2]]
            
            candidates = collections if collections else products_or_articles
            if not candidates:
                return None, None
                
            if article_context:
                import hashlib
                # Stable hash selection to distribute links evenly across articles
                idx = int(hashlib.md5(article_context.encode("utf-8")).hexdigest(), 16) % len(candidates)
                url, anchor, _ = candidates[idx]
            else:
                url, anchor, _ = candidates[0]
            return url, anchor
        return None, None


# ══════════════════════════════════════════════════════════════════════════════
# LINK INJECTION & SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def find_unlinked_keywords(article_text: str, existing_links: Set[str], link_map: LinkMap, article_context: str = None) -> List[Dict]:
    """
    Scan article for keywords that appear in link_map but are not yet linked.
    Returns list of {keyword, url, anchor_text, count, relevance_score} sorted by priority.
    """
    suggestions = []
    article_lower = article_text.lower()

    # Extract keywords with scores (prioritizes 2-word pairs & contextual modifiers)
    scored_keywords = extract_high_value_keywords(article_text)

    # Build lookup: for each scored keyword, find its URL target
    for keyword, relevance_score in scored_keywords:
        if not keyword:
            continue

        # Find URL in link_map (try exact match first, then substring)
        url, anchor_text = link_map.find_link_for_keyword(keyword, article_context)
        if not url:
            continue

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
                "first_position": matches[0].start(),
                "relevance_score": relevance_score
            })

    # Sort by relevance_score first (highest priority), then by position
    return sorted(suggestions, key=lambda x: (-x["relevance_score"], x["first_position"]))


def clean_previous_widgets(html_str: str) -> str:
    import re
    from bs4 import BeautifulSoup
    if not html_str:
        return ""

    # 1. Regex remove comments
    html_str = re.sub(r'<!--\s*meeeshop-shop-the-look-start\s*-->[\s\S]*?<!--\s*meeeshop-shop-the-look-end\s*-->', '', html_str)
    html_str = html_str.replace("meeeshop-shop-the-look-start", "").replace("meeeshop-shop-the-look-end", "")

    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div
    if not root:
        return html_str

    for h3 in root.find_all("h3"):
        if h3.get_text().strip().lower() == "shop the look":
            h3.decompose()

    for div in root.find_all("div"):
        if div.attrs is None:
            continue
        style = div.get("style", "") or ""
        style = style.replace(" ", "").lower()
        if "display:grid" in style and "grid-template-columns" in style:
            div.decompose()
            continue
        if "border:1pxsolid#f0f0f0" in style or "background:#fff" in style:
            div.decompose()
            continue

    for hr in root.find_all("hr"):
        style = hr.get("style", "") or ""
        style = style.replace(" ", "").lower()
        if "border-top:1pxsolid#eee" in style:
            hr.decompose()

    return "".join(str(c) for c in root.contents).strip()


def inject_link_into_html(html: str, keyword: str, url: str, anchor_text: str) -> Tuple[str, bool]:
    """
    Inject an <a> tag for the first unlinked occurrence of keyword in HTML.
    Avoids linking text that's already inside an <a> tag or tag attributes (alt, title, etc).
    Returns (modified_html, was_link_injected).
    """
    from bs4 import BeautifulSoup, NavigableString

    if not html:
        return "", False

    existing_links = extract_existing_links(html)
    if url.lower() in existing_links:
        return html, False

    # Standardize HTML wrapping to avoid BeautifulSoup adding <html>/<body> tags
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    root = soup.div
    if not root:
        return html, False

    # Find all text nodes that are NOT descendants of 'a', 'script', 'style', or product cards
    text_nodes = []
    for node in root.find_all(string=True):
        parent = node.parent
        in_forbidden_tag = False
        while parent and parent != root:
            if parent.name in ('a', 'script', 'style'):
                in_forbidden_tag = True
                break
            # Skip linking inside product cards and related products sections
            if parent.name == 'div' and parent.get('style'):
                style_str = parent.get('style', '').replace(' ', '')
                if 'background:#f8f6f3' in style_str or 'background:#fafafa' in style_str or 'background:#f0ede8' in style_str:
                    in_forbidden_tag = True
                    break
            parent = parent.parent
        if not in_forbidden_tag:
            text_nodes.append(node)

    pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
    was_injected = False

    for node in text_nodes:
        node_text = str(node)
        match = pattern.search(node_text)
        if match:
            # We found the first unlinked match!
            start, end = match.span()
            matched_text = node_text[start:end]

            # Create the new <a> tag
            link_tag = soup.new_tag("a", href=url)
            link_tag.string = matched_text

            # Get before and after text strings
            before_text = node_text[:start]
            after_text = node_text[end:]

            # Replace the old text node with: before_text, link_tag, after_text
            parent = node.parent
            if parent:
                try:
                    idx = parent.contents.index(node)
                    node.extract()

                    # Insert back in reverse order at the same index
                    if after_text:
                        parent.insert(idx, NavigableString(after_text))
                    parent.insert(idx, link_tag)
                    if before_text:
                        parent.insert(idx, NavigableString(before_text))

                    was_injected = True
                    break
                except ValueError:
                    continue

    if was_injected:
        # Reconstruct the inner HTML contents
        res_html = "".join(str(c) for c in root.contents)
        return res_html, True

    return html, False



# Global cache for collection lookups
COLLECTION_HANDLE_TO_ID = {}
COLLECTION_ID_TO_PRODUCTS = {}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def build_link_map() -> LinkMap:
    """Build keyword → URL map from all products, collections, and articles."""
    logger.info("Building link map...")
    link_map = LinkMap()

    # Add products for direct link matching
    logger.info("  Fetching products...")
    try:
        products = fetch_all_products()
        for product in products:
            title = product.get("title", "")
            handle = product.get("handle", "")
            if title and handle:
                link_map.add_product(title, handle)
        logger.info(f"    Added {len(products)} products")
    except Exception as e:
        logger.error(f"Failed to fetch products: {e}")

    # Add collections
    logger.info("  Fetching collections...")
    collections = fetch_all_collections()
    for collection in collections:
        title = collection.get("title", "")
        handle = collection.get("handle", "")
        cid = collection.get("id")
        if handle and cid:
            COLLECTION_HANDLE_TO_ID[handle] = cid
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


def filter_suggestions_with_ai(article_text: str, suggestions: List[Dict]) -> List[Dict]:
    """Use AI to prune and rank suggestions based on natural flow and context."""
    if not suggestions:
        return []
    
    items = []
    for idx, sug in enumerate(suggestions):
        items.append(f"{idx}: Keyword '{sug['keyword']}' -> Target '{sug['url']}'")
        
    prompt = (
        f"You are an expert copywriter and SEO optimizer.\n"
        f"Review this blog article excerpt and a list of proposed internal link insertions. "
        f"Determine which of the proposed links are highly contextually relevant and read naturally "
        f"in the text. Return only a comma-separated list of the indices (e.g. '0, 2') of the "
        f"good suggestions. Keep only the best ones.\n\n"
        f"Article:\n{article_text[:1500]}\n\n"
        f"Proposed Links:\n" + "\n".join(items) + "\n\n"
        f"Good Indices:"
    )
    
    try:
        response = generate(prompt, max_tokens=50, temperature=0.2)
        if response:
            valid_indices = []
            for item in response.split(","):
                clean_item = "".join(filter(str.isdigit, item))
                if clean_item:
                    valid_indices.append(int(clean_item))
            filtered = [suggestions[i] for i in valid_indices if i < len(suggestions)]
            return filtered
    except Exception as e:
        logger.warning(f"AI filtering failed: {e}. Falling back to default suggestions.")
    return suggestions


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

            # Check existing links for 404s
            broken_links = []
            for link in existing_links:
                full_link = link if link.startswith("http") else f"{SITE.rstrip('/')}{link}"
                try:
                    r = requests.head(full_link, allow_redirects=True, timeout=5)
                    if r.status_code == 404:
                        logger.warning(f"  [404 Alert] Found broken link in article '{article_title}': {link}")
                        broken_links.append(link)
                except Exception as e:
                    logger.debug(f"Failed to check link {link}: {e}")

            # Find unlinked keywords
            suggestions = find_unlinked_keywords(body_html, existing_links, link_map, article_context=article_title)

            # AI-assisted filtering
            if suggestions and (get_secret("GEMINI_API_KEY") or get_secret("GROQ_API_KEY") or get_secret("OPENROUTER_API_KEY")):
                logger.info(f"Article '{article_title}': running AI check on {len(suggestions)} suggestions")
                suggestions = filter_suggestions_with_ai(body_html, suggestions)

            modified_html = body_html
            injected_count = 0
            links_injected = []
            links_skipped = []

            if suggestions:
                logger.info(f"Article '{article_title}': {len(suggestions)} link suggestions (limiting to {max_links_per_article})")
                total_links_suggested += len(suggestions)

                # Inject links (with per-article limit)
                for suggestion in suggestions:
                    # HARD LIMIT: stop after max_links_per_article injected
                    if injected_count >= max_links_per_article:
                        links_skipped.append({
                            "keyword": suggestion["keyword"],
                            "reason": f"Limit reached ({max_links_per_article} max per article)"
                        })
                        continue

                    keyword = suggestion["keyword"]
                    url = suggestion["url"]
                    anchor_text = suggestion["anchor_text"]
                    mention_count = suggestion["count"]

                    # Check if collection is empty or low stock before linking to it
                    if "/collections/" in url:
                        handle_part = url.split("/collections/")[-1].split("?")[0].strip("/")
                        cid = COLLECTION_HANDLE_TO_ID.get(handle_part)
                        if cid:
                            in_stock_prods = fetch_products_for_collection(cid)
                            if len(in_stock_prods) < 2:
                                logger.info(f"  ⊘ Skipping low-stock/empty collection '{handle_part}' ({len(in_stock_prods)} products in stock)")
                                links_skipped.append({
                                    "keyword": keyword,
                                    "reason": f"Collection '{handle_part}' has only {len(in_stock_prods)} in-stock products"
                                })
                                continue

                    new_html, was_injected = inject_link_into_html(modified_html, keyword, url, anchor_text)

                    if was_injected:
                        modified_html = new_html
                        injected_count += 1
                        links_injected.append({
                            "keyword": keyword,
                            "target_url": url,
                            "anchor_text": anchor_text,
                            "occurrences_in_article": mention_count
                        })
                        logger.info(f"  ✓ Linked '{keyword}' ({mention_count} mentions) → {url}")
                    else:
                        links_skipped.append({
                            "keyword": keyword,
                            "reason": "Already linked or regex match failed"
                        })
                        logger.debug(f"  ⊘ Skipped '{keyword}' (already linked)")

            # Check for collection links in the final HTML to inject "Shop the Look"
            final_links = extract_existing_links(modified_html)
            collection_handles = []
            for link in final_links:
                m = re.search(r'/collections/([a-zA-Z0-9_-]+)', link)
                if m:
                    handle = m.group(1)
                    if handle in COLLECTION_HANDLE_TO_ID:
                        collection_handles.append(handle)

            widget_added = False
            # Find the first collection that has in-stock products and append the widget
            for handle in collection_handles:
                cid = COLLECTION_HANDLE_TO_ID[handle]
                in_stock_prods = fetch_products_for_collection(cid)
                if len(in_stock_prods) >= 2:
                    # Clean previous widget if present
                    clean_html = clean_previous_widgets(modified_html)
                    
                    # Generate dynamic widget HTML
                    widget_html = (
                        "\n\n<!-- meeeshop-shop-the-look-start -->\n"
                        '<hr style="border: 0; border-top: 1px solid #eee; margin: 40px 0;">\n'
                        '<h3 style="text-align: center; margin-bottom: 20px; font-family: sans-serif; letter-spacing: 1px;">Shop the Look</h3>\n'
                        '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px;">\n'
                    )
                    for p in in_stock_prods[:4]:
                        raw_title = p.get("title", "")
                        escaped_title = html.escape(raw_title)
                        alt_title = raw_title.replace('"', "'")
                        p_handle = p.get("handle", "")
                        price = p.get("variants", [{}])[0].get("price", "0.00")
                        img_src = p.get("images", [{}])[0].get("src", "")
                        
                        widget_html += (
                            f'  <div style="border: 1px solid #f0f0f0; padding: 10px; text-align: center; border-radius: 8px; background: #fff;">\n'
                            f'    <a href="{SITE}/products/{p_handle}" style="text-decoration: none; color: #333;">\n'
                        )
                        if img_src:
                            widget_html += f'      <img src="{img_src}" alt="{alt_title}" style="width: 100%; max-height: 200px; object-fit: cover; border-radius: 4px; margin-bottom: 8px;">\n'
                        widget_html += (
                            f'      <div style="font-size: 13px; font-weight: bold; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{escaped_title}</div>\n'
                            f'      <div style="font-size: 12px; color: #888;">${price}</div>\n'
                            f'    </a>\n'
                            f'  </div>\n'
                        )
                    widget_html += "</div>\n<!-- meeeshop-shop-the-look-end -->\n"
                    
                    modified_html = clean_html.strip() + "\n\n" + widget_html
                    widget_added = True
                    break # Append exactly one widget per article

            # If HTML changed (either links injected or widget added), update Shopify
            if modified_html != body_html:
                total_links_injected += injected_count
                
                article_log = {
                    "article_title": article_title,
                    "article_url": article_url,
                    "blog_name": blog_title,
                    "links_injected": links_injected,
                    "links_skipped": links_skipped,
                    "widget_added": widget_added,
                    "broken_links_detected": broken_links
                }
                detailed_log.append(article_log)

                if apply:
                    if update_article(blog_id, article_id, modified_html):
                        logger.info(f"  ✓ Updated article (links={injected_count}, widget={widget_added})")
                    else:
                        logger.error(f"  ✗ Failed to update article")
                else:
                    logger.info(f"  [DRY RUN] Would update article (links={injected_count}, widget={widget_added})")

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
