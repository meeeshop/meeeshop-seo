import os
import sys
import logging
import requests
import random
import json
import time
import argparse
import re
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decrypt secrets via secrets_manager (double-Fernet) then read from env.
# ---------------------------------------------------------------------------
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from secrets_manager import inject_to_env
    inject_to_env()
    _log.info("[secrets] inject_to_env() succeeded")
except Exception as _e:
    _log.critical("[secrets] inject_to_env() FAILED — script cannot run: %s", _e, exc_info=True)
    sys.exit(1)

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")

if not SHOPIFY_STORE or not SHOPIFY_TOKEN or not OPENROUTER_KEY:
    _log.critical("[secrets] One or more required secrets are empty after decryption: "
                  "SHOPIFY_STORE=%s, SHOPIFY_ACCESS_TOKEN=%s, OPENROUTER_API_KEY=%s",
                  bool(SHOPIFY_STORE), bool(SHOPIFY_TOKEN), bool(OPENROUTER_KEY))
    sys.exit(1)

#Stable free-tier models (May 2026)
MODEL_CHAIN = [
    "meta/llama-3.2-3b-instruct:free",
    "google/gemini-pro-1.5:free",
    "mistralai/mistral-7b-instruct:free",
    "anthropic/claude-3-haiku:free",
    "cohere/command-r-plus:free",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_json(text: str) -> dict:
    """Extract the first {...} block from a string and parse it as JSON."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(match.group(0))


def safe_request(
    method: str,
    url: str,
    headers: dict | None = None,
    json_payload: dict | None = None,
    timeout: int = 60,
    max_retries: int = 3,
    verify_ssl: bool = False,          # GitHub runners sometimes have cert issues
) -> requests.Response:
    """Wrapper around requests.request with retries and clearer error logging."""
    headers = headers or {}
    # Shopify recommends a descriptive User‑Agent
    headers.setdefault("User-Agent", "ShopifyBlogBot/1.0 (+https://github.com/meeeshop)")

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_payload,
                timeout=timeout,
                verify=verify_ssl,
            )
            # Log status for debugging
            if resp.status_code == 403:
                print(
                    f"❌ 403 Forbidden – URL: {url}\n"
                    f"   Headers sent: {list(headers.keys())}\n"
                    "   Possible causes: wrong token, missing scopes (read_content/write_content), "
                    "trial store, or IP restriction."
                )
            elif 400 <= resp.status_code < 600:
                print(f"⚠️  HTTP {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                raise
            print(f"   Retry {attempt}/{max_retries} after error: {e}")
            time.sleep(5)
    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# OpenRouter LLM call
# ---------------------------------------------------------------------------

def call_llm(prompt: str) -> str:
    """Try each model in MODEL_CHAIN until one succeeds."""
    if not OPENROUTER_KEY:
        raise ValueError("OPENROUTER_KEY is not set")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }

    for model in MODEL_CHAIN:
        print(f"🤖 Trying model: {model}")
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            print(f"   Model {model} returned {resp.status_code}")
        except Exception as e:
            print(f"   Model {model} error: {e}")
    raise Exception("All OpenRouter models failed")


# ---------------------------------------------------------------------------
# Blog content generation
# ---------------------------------------------------------------------------

def generate_blogpost() -> dict:
    topics = [
        "Linen Summer Outfits for USA Women",
        "USA Women Fashion Trends 2026",
        "Minimalist Wardrobe Guide for Professionals",
        "Casual Chic Streetwear Ideas",
        "Sustainable Fashion Choices for Spring/Summer",
    ]
    topic = random.choice(topics)

    prompt = f"""Return ONLY valid JSON (no markdown, no code fences):
{{
  "title": "An SEO-friendly blog post title",
  "body_html": "Full HTML blog post body, 1500+ words, rich with <p>, <h2>, <h3>, <ul>, <li> tags. Target audience: USA women fashion shoppers."
}}

Topic: {topic}
"""

    print(f"📡 Generating blog post for topic: {topic}")
    raw = call_llm(prompt)
    data = clean_json(raw)

    if "title" not in data or "body_html" not in data:
        raise ValueError("LLM response missing required fields")
    return data


# ---------------------------------------------------------------------------
# Shopify API helpers
# ---------------------------------------------------------------------------

def get_shopify_blog() -> dict:
    """Find the first blog that looks like a 'News' or 'Blog' channel."""
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    }
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/blogs.json"
    resp = safe_request("GET", url, headers=headers)
    blogs = resp.json().get("blogs", [])
    if not blogs:
        raise Exception("No blogs found in Shopify store")

    # Prefer a blog whose title contains 'news' or 'blog'
    for blog in blogs:
        title_lower = blog.get("title", "").lower()
        if "news" in title_lower or "blog" in title_lower:
            print(f"✅ Found blog: {blog['title']} (id={blog['id']})")
            return blog

    # Fallback: use the first blog
    print(f"⚠️  Using first available blog: {blogs[0]['title']}")
    return blogs[0]


def publish_article(blog: dict, data: dict) -> dict:
    """Post a new article to the given Shopify blog."""
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {
        "article": {
            "title": data["title"],
            "body_html": data["body_html"],
            "published": True,
            "published_at": datetime.utcnow().isoformat() + "Z",
            "author": "AI Fashion Writer",
        }
    }
    url = (
        f"https://{SHOPIFY_STORE}/admin/api/2024-04/"
        f"blogs/{blog['id']}/articles.json"
    )
    print(f"🚀 Posting article '{data['title']}' to blog '{blog['title']}'")
    resp = safe_request("POST", url, headers=headers, json_payload=payload)
    article = resp.json().get("article")
    if not article:
        raise ValueError("Shopify did not return article data")
    print(
        f"✅ Published: https://{SHOPIFY_STORE}/blogs/{blog['handle']}/{article['handle']}"
    )
    return article


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate and publish Shopify blog posts via OpenRouter"
    )
    parser.add_argument("--api-key", help="OpenRouter API key (overrides env)")
    parser.add_argument("--shopify-store", help="Shopify store URL (overrides env)")
    parser.add_argument("--shopify-token", help="Shopify access token (overrides env)")
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help="Skip generation, only publish existing draft (not implemented yet)",
    )
    args = parser.parse_args()

    # Override from CLI args
    global OPENROUTER_KEY, SHOPIFY_STORE, SHOPIFY_TOKEN
    if args.api_key:
        OPENROUTER_KEY = args.api_key
    if args.shopify_store:
        SHOPIFY_STORE = args.shopify_store
    if args.shopify_token:
        SHOPIFY_TOKEN = args.shopify_token

    # Basic validation
    if not SHOPIFY_STORE or not SHOPIFY_TOKEN:
        raise ValueError(
            "Shopify credentials missing. Set SHOPIFY_STORE and SHOPIFY_TOKEN "
            "environment variables or use --shopify-store / --shopify-token."
        )
    if not OPENROUTER_KEY:
        raise ValueError(
            "OpenRouter API key missing. Set OPENROUTER_KEY environment variable or use --api-key."
        )

    # Strip protocol if user accidentally included it
    SHOPIFY_STORE = SHOPIFY_STORE.replace("https://", "").replace("http://", "").rstrip("/")

    if args.publish_only:
        print("⚠️  --publish-only is not fully implemented; generating and publishing instead.")
        # In a real scenario you would load a previously generated draft here.

    blog = get_shopify_blog()
    data = generate_blogpost()
    publish_article(blog, data)
    print(f"Review + publish at: https://{SHOPIFY_STORE}/admin/articles\n")


if __name__ == "__main__":
    main()
