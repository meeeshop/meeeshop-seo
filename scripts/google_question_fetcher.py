#!/usr/bin/env python3
"""
google_question_fetcher.py — Live US Google Search Question Fetcher for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Queries Google Autocomplete API (gl=us&hl=en) for real-time US search questions across
12 core e-commerce categories:
  1. Styling & Pairing
  2. Fit & Sizing
  3. Care, Cleaning & Maintenance
  4. Fabrics & Material Quality
  5. Occasions & Suitability
  6. Trends & Longevity
  7. Body Shape & Flattering Fits
  8. Age-Specific Style Advice
  9. Color Coordination & Palettes
  10. Weather & Temperature Transitions
  11. Undergarments & Wardrobe Hacks
  12. Budget, Quality & Shopping Comparisons

Maintains persistent history in addressed_questions_history.json.
Deduplicates exact matches while respecting Smart Modifier Variations
(e.g., "over 40", "for petite", "for work", "in winter" are valid distinct topics).
"""

import os
import sys
import re
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
HISTORY_FILE = SCRIPT_DIR / "addressed_questions_history.json"

# ── 12-Category Question Stems ────────────────────────────────────────────────
QUESTION_STEM_PATTERNS = [
    # 1. Styling & Pairing
    "how to style {product}",
    "what shoes to wear with {product}",
    "what tops go with {product}",
    "how to layer {product}",
    "what jacket to wear with {product}",
    # 2. Fit & Sizing
    "how should {product} fit",
    "does {product} run big or small",
    "how to size {product}",
    "how to shrink {product}",
    "how to stretch {product}",
    # 3. Care, Cleaning & Maintenance
    "how to wash {product}",
    "how to clean {product}",
    "how to care for {product}",
    "how to remove stains from {product}",
    # 4. Fabrics & Material Quality
    "what fabric is best for {product}",
    "is {product} see through",
    "does {product} wrinkle",
    "does {product} shrink",
    # 5. Occasions & Suitability
    "can you wear {product} to a wedding",
    "is {product} business casual",
    "can you wear {product} to work",
    # 6. Trends & Longevity
    "is {product} still in style in 2026",
    "is {product} out of style",
    "best alternative to {product}",
    # 7. Body Shape & Flattering Fits
    "what {product} looks best on curvy",
    "what {product} looks best on petite",
    "what {product} hides belly fat",
    "how to style {product} for pear shape",
    # 8. Age-Specific Style Advice
    "how to style {product} over 40",
    "how to style {product} over 50",
    "casual chic {product} for 30s",
    # 9. Color Coordination & Palettes
    "what color shoes go with {product}",
    "what colors complement {product}",
    # 10. Weather & Temperature Transitions
    "what to wear with {product} in 60 degree weather",
    "how to style {product} in fall",
    "how to style {product} in winter",
    # 11. Undergarments & Wardrobe Hacks
    "what bra to wear with {product}",
    "best shapewear under {product}",
    # 12. Budget, Quality & Shopping Comparisons
    "affordable boutique {product} under 50",
    "how to make {product} look expensive"
]

# Modifiers that define distinct intent variations
INTENT_MODIFIERS = [
    # Age
    "over 40", "over 50", "over 60", "30s", "20s", "teens",
    # Body shape
    "petite", "curvy", "plus size", "pear shape", "apple shape", "tall", "midsize", "hourglass",
    # Occasion / Setting
    "wedding", "work", "office", "date night", "casual", "formal", "party", "brunch",
    # Season / Weather
    "summer", "winter", "fall", "autumn", "spring", "60 degree", "cold weather", "hot weather",
    # Material
    "linen", "silk", "cotton", "leather", "satin", "denim"
]


class GoogleQuestionFetcher:

    def __init__(self, history_path: Path = HISTORY_FILE):
        self.history_path = history_path
        self.history = self._load_history()

    def _load_history(self) -> dict:
        if self.history_path.exists():
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[QuestionFetcher] Warning: failed to load history: {e}")
        return {}

    def _save_history(self):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[QuestionFetcher] Warning: failed to save history: {e}")

    @staticmethod
    def extract_modifiers(text: str) -> tuple[str, ...]:
        """Extract sorted list of distinct intent modifiers from text."""
        t_lower = text.lower()
        found = []
        for mod in INTENT_MODIFIERS:
            if re.search(r"\b" + re.escape(mod) + r"\b", t_lower):
                found.append(mod)
        return tuple(sorted(found))

    @staticmethod
    def normalize_question(question: str) -> str:
        """Clean and normalize raw Google question."""
        q = question.strip()
        if not q:
            return ""
        # Capitalize first letter
        q = q[0].upper() + q[1:]
        # Ensure proper ending
        if not q.endswith("?") and not q.endswith("."):
            q += "?"
        return q

    def _get_signature(self, question: str) -> tuple[str, tuple[str, ...]]:
        """
        Returns (base_fingerprint, modifiers_tuple).
        Two questions match ONLY if base_fingerprint is identical AND modifiers_tuple is identical.
        """
        q_clean = question.lower()
        q_clean = re.sub(r"\b20\d\d\b", "", q_clean)  # Strip years
        q_clean = re.sub(r"[^\w\s]", " ", q_clean)
        q_clean = re.sub(r"\s+", " ", q_clean).strip()

        mods = self.extract_modifiers(question)
        # Remove modifier words from base fingerprint
        base = q_clean
        for m in mods:
            base = re.sub(r"\b" + re.escape(m) + r"\b", "", base)
        base = re.sub(r"\s+", " ", base).strip()

        return base, mods

    def is_addressed(self, question: str, deduplicator=None) -> bool:
        """
        Checks if the question (or exact modifier combo) has already been addressed
        in local history OR live Shopify article titles/handles.
        """
        sig = self._get_signature(question)
        sig_str = f"{sig[0]}||{','.join(sig[1])}"

        # 1. Check local history
        if sig_str in self.history:
            return True

        # 2. Check ArticleDeduplicator (live Shopify titles/handles)
        if deduplicator and hasattr(deduplicator, "is_duplicate_question"):
            if deduplicator.is_duplicate_question(question, modifiers=sig[1]):
                return True

        return False

    def mark_addressed(self, question: str, category: str = "general", article_id: str = None):
        """Register a question as addressed."""
        sig = self._get_signature(question)
        sig_str = f"{sig[0]}||{','.join(sig[1])}"
        self.history[sig_str] = {
            "question": question,
            "category": category,
            "article_id": article_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._save_history()

    def fetch_live_google_questions(self, product_type: str, limit: int = 15) -> list[str]:
        """
        Queries Google Autocomplete API (US locale) across 12 category stems
        for a given product_type.
        """
        clean_product = product_type.lower().strip()
        # Handle plural vs singular mapping
        product_query = clean_product
        if clean_product in ["jean", "jeans", "denim"]:
            product_query = "jeans"
        elif clean_product in ["dress", "dresses"]:
            product_query = "dresses"
        elif clean_product in ["shacket", "shackets"]:
            product_query = "shacket"
        elif clean_product in ["coat", "coats", "jacket", "jackets"]:
            product_query = "jackets"
        elif clean_product in ["top", "tops", "blouse", "blouses"]:
            product_query = "tops"

        results = []
        seen = set()

        for pattern in QUESTION_STEM_PATTERNS:
            stem_query = pattern.format(product=product_query)
            url = (
                f"http://suggestqueries.google.com/complete/search"
                f"?client=chrome&gl=us&hl=en&q={urllib.parse.quote(stem_query)}"
            )
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if len(data) > 1 and isinstance(data[1], list):
                        for suggestion in data[1]:
                            norm = self.normalize_question(suggestion)
                            if norm and norm not in seen:
                                seen.add(norm)
                                results.append(norm)
            except Exception as e:
                print(f"[QuestionFetcher] Query failed for '{stem_query}': {e}")
                continue

            if len(results) >= limit * 2:
                break

        return results

    def get_next_unaddressed_question(self, product_type: str, deduplicator=None, default_fallback: str = None) -> str:
        """
        Fetches live questions from Google for product_type, iterates through them,
        and returns the FIRST question that has not been addressed yet.
        """
        questions = self.fetch_live_google_questions(product_type, limit=20)

        for q in questions:
            if not self.is_addressed(q, deduplicator):
                print(f"  [OK] Selected unaddressed Google Question for '{product_type}': {q}")
                return q

        # If all live suggestions were addressed or API returned empty, return fallback question
        fallback = default_fallback or f"How to Style {product_type.title()} for Everyday Chic"
        print(f"  [!] All Google suggestions addressed or empty. Using fallback question: {fallback}")
        return self.normalize_question(fallback)


# Standalone CLI test
if __name__ == "__main__":
    fetcher = GoogleQuestionFetcher()
    test_ptype = sys.argv[1] if len(sys.argv) > 1 else "jeans"
    print(f"\n--- Testing Google Question Fetcher for '{test_ptype}' ---")
    qs = fetcher.fetch_live_google_questions(test_ptype, limit=10)
    print(f"Fetched {len(qs)} live questions:")
    for idx, q in enumerate(qs[:10], 1):
        is_add = fetcher.is_addressed(q)
        print(f" {idx}. [{ 'X' if is_add else 'NEW' }] {q}")

    selected = fetcher.get_next_unaddressed_question(test_ptype)
    print(f"\nSelected Question: {selected}")
