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

# Male / Men's terms to strictly exclude (MeeeShop is 100% Women's Boutique)
MENS_TERMS = {
    "men", "mens", "men's", "man", "mans", "man's", "guy", "guys", "male", "males",
    "boy", "boys", "boy's", "husband", "boyfriend", "father", "dad", "groom", "groomsmen", "groomsman"
}

# Non-US countries, regions, cities, and currency terms to strictly exclude (Target audience is 100% US)
NON_US_LOCATION_TERMS = {
    "uk", "united kingdom", "england", "scotland", "wales", "britain", "british", "great britain",
    "australia", "australian", "oz", "aus",
    "canada", "canadian",
    "new zealand", "nz", "zealand", "kiwi",
    "ireland", "irish",
    "europe", "european", "eu",
    "germany", "german", "france", "french", "italy", "italian", "spain", "spanish",
    "india", "indian", "japan", "japanese", "china", "chinese", "mexico", "mexican",
    "asia", "asian", "africa", "african",
    "london", "sydney", "melbourne", "birmingham", "manchester", "glasgow", "edinburgh",
    "brisbane", "perth", "adelaide", "toronto", "vancouver", "montreal", "calgary", "ottawa",
    "auckland", "wellington", "dublin", "paris", "berlin", "tokyo", "rome", "madrid",
    "gbp", "aud", "cad", "nzd", "eur"
}

# Competitor retailers & marketplace terms to strictly exclude unless matching brand/vendor name
COMPETITOR_RETAILER_TERMS = {
    "amazon", "walmart", "target", "shein", "temu", "next", "nordstrom", "macys", "macy's",
    "ebay", "zappos", "express", "asos", "boohoo", "fashion nova", "fashionnova", "lulus",
    "tj maxx", "tjmaxx", "marshalls", "kohls", "kohl's", "old navy", "gap", "h&m", "hm",
    "zara", "forever 21", "forever21", "urban outfitters", "pacsun", "etsy", "aliexpress",
    "wish", "poshmark", "mercari", "thredup", "depop", "dillards", "bloomingdales", "saks",
    "neiman marcus", "jcpenney", "belk", "loft", "ann taylor", "maurices", "charlotte russe",
    "rue21", "wet seal", "tillys", "buckle", "francesca's", "francescas", "altard state",
    "altardstate", "red dress boutique", "pink lily", "boho pink", "vici", "vici dolls"
}

# Brick-and-mortar / physical store local intent terms to strictly exclude (MeeeShop is 100% online)
LOCAL_BRICK_MORTAR_TERMS = {
    "near me", "near my location", "nearby", "in my area", "store locator",
    "physical store", "brick and mortar", "local store", "store near me",
    "boutique near me", "shop near me", "outlet near me", "pickup near me"
}

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

    @staticmethod
    def is_for_women_only(question: str) -> bool:
        """Return True if question contains NO male / men's terms."""
        if not question:
            return False
        words = re.findall(r"\b\w+'?\w*\b", question.lower())
        for w in words:
            if w in MENS_TERMS:
                return False
        return True

    @staticmethod
    def has_non_us_location(text: str) -> bool:
        """Return True if text contains non-US country, region, city, or currency terms."""
        if not text:
            return False
        words = set(re.findall(r"\b\w+'?\w*\b", text.lower()))
        if words.intersection(NON_US_LOCATION_TERMS):
            return True
        t_lower = text.lower()
        for mw in ["united kingdom", "new zealand", "great britain", "northern ireland"]:
            if mw in t_lower:
                return True
        return False

    @classmethod
    def remove_non_us_locations(cls, text: str) -> str:
        """Sanitize text by removing non-US location words and cleaning punctuation/grammar."""
        if not text:
            return text
        cleaned = text
        for mw in ["united kingdom", "new zealand", "great britain", "northern ireland"]:
            cleaned = re.sub(r"\b" + re.escape(mw) + r"\b", "", cleaned, flags=re.IGNORECASE)
        single_words = sorted([w for w in NON_US_LOCATION_TERMS if " " not in w], key=len, reverse=True)
        pattern = r"\b(?:" + "|".join(re.escape(w) for w in single_words) + r")\b"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        
        # Clean dangling conjunctions and prepositions left behind
        cleaned = re.sub(r"\b(in|at|from|and|or|&)\s+(?=and|or|&|\b)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(in|at|from|and|or|&)\s*(?=[,.!?|]|$)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"&\s*\|", "|", cleaned)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
        
        # Deduplicate adjacent comma-separated terms
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        dedup = []
        for p in parts:
            if not dedup or p.lower() != dedup[-1].lower():
                dedup.append(p)
        return ", ".join(dedup)

    @staticmethod
    def has_competitor_retailer(text: str, allowed_brand: str = "") -> bool:
        """Return True if text contains competitor retailer names (unless matching allowed_brand)."""
        if not text:
            return False
        allowed = allowed_brand.lower().strip() if allowed_brand else ""
        words = set(re.findall(r"\b\w+'?\w*\b", text.lower()))
        for term in COMPETITOR_RETAILER_TERMS:
            if allowed and term in allowed:
                continue
            if " " in term:
                if re.search(r"\b" + re.escape(term) + r"\b", text.lower()):
                    return True
            else:
                if term in words:
                    return True
        return False

    @classmethod
    def remove_competitor_retailers(cls, text: str, allowed_brand: str = "") -> str:
        """Sanitize text by removing competitor retailer names unless matching allowed_brand."""
        if not text:
            return text
        allowed = allowed_brand.lower().strip() if allowed_brand else ""
        cleaned = text
        multi_words = sorted([t for t in COMPETITOR_RETAILER_TERMS if " " in t], key=len, reverse=True)
        for mw in multi_words:
            if allowed and mw in allowed:
                continue
            cleaned = re.sub(r"\b" + re.escape(mw) + r"\b", "", cleaned, flags=re.IGNORECASE)
        single_words = sorted([t for t in COMPETITOR_RETAILER_TERMS if " " not in t], key=len, reverse=True)
        single_filtered = [w for w in single_words if not (allowed and w in allowed)]
        pattern = r"\b(?:" + "|".join(re.escape(w) for w in single_filtered) + r")\b"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"\b(at|on|from|in|by|and|or|&)\s+(?=and|or|&|\b)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(at|on|from|in|by|and|or|&)\s*(?=[,.!?|]|$)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"&\s*\|", "|", cleaned)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
        
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        dedup = []
        for p in parts:
            if not dedup or p.lower() != dedup[-1].lower():
                dedup.append(p)
        return ", ".join(dedup)

    @staticmethod
    def has_local_intent(text: str) -> bool:
        """Return True if text contains local brick-and-mortar search terms like 'near me'."""
        if not text:
            return False
        t_lower = text.lower()
        for term in LOCAL_BRICK_MORTAR_TERMS:
            if re.search(r"\b" + re.escape(term) + r"\b", t_lower):
                return True
        return False

    @classmethod
    def remove_local_intent(cls, text: str) -> str:
        """Sanitize text by removing 'near me' and local physical store terms."""
        if not text:
            return text
        cleaned = text
        sorted_terms = sorted(list(LOCAL_BRICK_MORTAR_TERMS), key=len, reverse=True)
        for term in sorted_terms:
            cleaned = re.sub(r"\b" + re.escape(term) + r"\b", "", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"\b(at|on|from|in|by|and|or|&)\s+(?=and|or|&|\b)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(at|on|from|in|by|and|or|&)\s*(?=[,.!?|]|$)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"&\s*\|", "|", cleaned)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
        
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        dedup = []
        for p in parts:
            if not dedup or p.lower() != dedup[-1].lower():
                dedup.append(p)
        return ", ".join(dedup)

    @classmethod
    def remove_disallowed_terms(cls, text: str, allowed_brand: str = "") -> str:
        """Master sanitizer: removes non-US locations, competitor retailers, and local 'near me' terms."""
        if not text:
            return text
        c = cls.remove_non_us_locations(text)
        c = cls.remove_competitor_retailers(c, allowed_brand)
        c = cls.remove_local_intent(c)
        return c


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

    @staticmethod
    def _get_stem_family(question: str) -> str:
        """Categorize a question into its core stem family / angle."""
        q_lower = question.lower()
        if any(x in q_lower for x in ["shoes", "shoe", "footwear", "sneakers", "heels", "boots"]):
            return "shoes_pairing"
        if "top" in q_lower or ("shirt" in q_lower and "go with" in q_lower):
            return "tops_pairing"
        if ("jacket" in q_lower or "coat" in q_lower) and "wear with" in q_lower:
            return "outerwear_pairing"
        if "layer" in q_lower:
            return "layering"
        if any(x in q_lower for x in ["wash", "clean", "care for", "stain"]):
            return "care_laundry"
        if any(x in q_lower for x in ["fit", "size", "shrink", "stretch"]):
            return "fit_sizing"
        if any(x in q_lower for x in ["wedding", "work", "business casual", "office"]):
            return "occasion"
        if any(x in q_lower for x in ["in style", "out of style", "trend"]):
            return "trend_longevity"
        if any(x in q_lower for x in ["curvy", "petite", "belly", "pear", "hourglass"]):
            return "body_shape"
        if any(x in q_lower for x in ["over 40", "over 50", "over 60", "30s"]):
            return "age_style"
        if any(x in q_lower for x in ["bra", "shapewear", "undergarment"]):
            return "undergarments"
        if "how to style" in q_lower:
            return "general_styling"
        return "general"

    def is_addressed(self, question: str, deduplicator=None, cooldown_days: int = 5) -> bool:
        """
        Checks if the question (or exact modifier combo) has already been addressed,
        or if a similar base topic or stem family was addressed within the 5-day cooldown window.
        """
        sig = self._get_signature(question)
        sig_str = f"{sig[0]}||{','.join(sig[1])}"
        stem_fam = self._get_stem_family(question)
        now = datetime.now(timezone.utc)

        # 1. Exact signature match check in local history
        if sig_str in self.history:
            return True

        # Extract key words
        stop_words = {"how", "to", "with", "the", "for", "and", "a", "an", "in", "or", "what", "is", "are", "do", "does", "can", "you", "wear", "style", "2026", "2025"}
        q_words = set(w for w in re.findall(r"\b[a-zA-Z]{3,}\b", question.lower()) if w not in stop_words)

        # 2. Base topic & Stem Family 5-day variation cooldown check
        for entry_sig, entry_data in self.history.items():
            entry_base = entry_sig.split("||")[0]
            entry_q = entry_data.get("question", "")
            entry_stem = self._get_stem_family(entry_q)

            if q_words:
                entry_words = set(w for w in re.findall(r"\b[a-zA-Z]{3,}\b", entry_q.lower()) if w not in stop_words)
                if entry_words and q_words.issubset(entry_words):
                    print(f"  [Dedup History] Question '{question}' key words fully covered in history '{entry_q}'")
                    return True

            ts_str = entry_data.get("timestamp")
            if ts_str:
                try:
                    entry_dt = datetime.fromisoformat(ts_str)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    if (now - entry_dt).total_seconds() < (cooldown_days * 86400):
                        if entry_base == sig[0]:
                            print(f"  [Dedup Cooldown] Base topic '{sig[0]}' addressed within last {cooldown_days} days — skipping variation '{question}'")
                            return True
                        if stem_fam != "general" and entry_stem == stem_fam:
                            print(f"  [Dedup Cooldown] Question stem family '{stem_fam}' addressed within last {cooldown_days} days — skipping '{question}' for stem diversity")
                            return True
                except Exception:
                    pass

        # 3. Check ArticleDeduplicator (live Shopify titles/handles)
        if deduplicator:
            if hasattr(deduplicator, "is_duplicate_question"):
                if deduplicator.is_duplicate_question(question, modifiers=sig[1]):
                    return True
            if hasattr(deduplicator, "is_duplicate_title"):
                if deduplicator.is_duplicate_title(question):
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
                            if norm and self.is_for_women_only(norm) and not self.has_non_us_location(norm) and not self.has_competitor_retailer(norm, allowed_brand=clean_product) and norm not in seen:
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
        Fetches live questions from Google for product_type, iterates through them in order,
        and returns the FIRST question that has NOT been addressed yet by our store.
        If all live suggestions are addressed, generates a fresh long-tail modifier variation.
        """
        questions = self.fetch_live_google_questions(product_type, limit=25)

        for q in questions:
            if not self.is_for_women_only(q) or self.has_non_us_location(q) or self.has_competitor_retailer(q, allowed_brand=product_type):
                continue
            if self.is_addressed(q, deduplicator):
                print(f"  [Waterfall] Question already addressed by store: '{q}' -> Trying next in line...")
                continue
            print(f"  [OK Deduplicated Question] Selected fresh Google question for '{product_type}': {q}")
            return q

        # Waterfall Fallback: Generate fresh long-tail modifier questions if all top queries are addressed
        clean_ptype = product_type.title()
        modifier_options = [
            f"How to Style {clean_ptype} for Women Over 40 in 2026?",
            f"What Shoes to Wear with {clean_ptype} for Casual Chic Outfits?",
            f"How Should {clean_ptype} Fit for Petite and Curvy Body Shapes?",
            f"How to Wash and Care for {clean_ptype} to Prevent Shrinking?",
            f"What Tops and Jackets Go Best with {clean_ptype} in 2026?",
            f"Can You Wear {clean_ptype} to Work or Business Casual Settings?",
            f"How to Layer {clean_ptype} for Transition Weather in 2026?",
            f"Best Undergarments and Shapewear to Wear Under {clean_ptype}?"
        ]

        for mod_q in modifier_options:
            if not self.is_addressed(mod_q, deduplicator):
                print(f"  [Waterfall Fallback] Selected unaddressed modified question: {mod_q}")
                return mod_q

        fallback = default_fallback or f"How to Style {clean_ptype} for Everyday Chic in 2026?"
        print(f"  [!] All suggestions & modifiers addressed. Using fallback question: {fallback}")
        return self.normalize_question(fallback)

    def fetch_pasf_modifiers(self, term: str) -> list[str]:
        """
        Queries Google Autocomplete API for search modifier terms (PASF equivalents)
        for a product type, sub-category, or vendor brand.
        Excludes male terms, non-US location terms, and competitor retailer names.
        """
        clean_term = term.lower().strip()
        url = (
            f"http://suggestqueries.google.com/complete/search"
            f"?client=chrome&gl=us&hl=en&q={urllib.parse.quote(clean_term)}"
        )
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        modifiers = []
        seen = set()

        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if len(data) > 1 and isinstance(data[1], list):
                    for suggestion in data[1]:
                        s_clean = suggestion.lower().strip()
                        # Extract the modifier beyond the main search term
                        mod = s_clean.replace(clean_term, "").strip()
                        if mod and self.is_for_women_only(mod) and not self.has_non_us_location(mod) and not self.has_competitor_retailer(mod, allowed_brand=clean_term) and mod not in seen:
                            seen.add(mod)
                            modifiers.append(mod)
        except Exception as e:
            print(f"[QuestionFetcher] PASF Query failed for '{term}': {e}")

        # Fallback default modifiers if autocomplete returns few results
        default_mods = ["size chart", "women", "high rise", "price", "where to buy", "sale", "outfit ideas"]
        for dm in default_mods:
            if dm not in seen:
                modifiers.append(dm)

        return modifiers[:8]




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
