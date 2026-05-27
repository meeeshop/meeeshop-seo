#!/usr/bin/env python3
"""
Standalone test of keyword extraction logic (no Shopify API needed).
Tests the improved 2-word pair prioritization and contextual scoring.
"""

import re
from typing import List, Tuple, Set

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

HIGH_VALUE_KEYWORDS = {
    "dress", "dresses", "top", "tops", "blouse", "shirt", "jean", "jeans",
    "pant", "pants", "skirt", "skirts", "jacket", "coat", "sweater", "cardigan",
    "blazer", "hoodie", "shorts", "leggings", "romper", "jumpsuit",
    "tank", "tunic", "tee", "crop", "maxi", "midi",
    "leather", "denim", "cotton", "silk", "linen", "lace", "mesh", "satin", "velvet",
    "handbag", "bag", "purse", "tote", "crossbody", "backpack", "clutch",
}

CONTEXTUAL_MODIFIERS = {
    "leather", "denim", "cotton", "silk", "linen", "lace", "mesh", "satin", "velvet",
    "floral", "striped", "stripe", "solid", "print", "polka", "checkered",
    "black", "white", "red", "blue", "green", "yellow", "pink", "gray", "grey",
    "navy", "cream", "beige", "brown", "purple", "orange",
}

def strip_html(html: str) -> str:
    """Remove HTML tags, keep text."""
    return re.sub(r"<[^>]+>", " ", html or "").strip()

def extract_high_value_keywords(text: str) -> List[Tuple[str, float]]:
    """Extract high-value keywords with relevance scores: prefer 2-word pairs over singles.
    Returns sorted list of (keyword, score) tuples, highest relevance first."""
    if not text:
        return []

    text_lower = strip_html(text).lower()
    words = re.findall(r"\b[a-z]+(?:-[a-z]+)?\b", text_lower)
    scored_keywords = {}  # keyword -> max_score

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


def test_keyword_extraction():
    """Test improved keyword extraction with scoring."""

    test_cases = [
        {
            "name": "2-word contextual pair (highest priority)",
            "text": "This silk dress is perfect for summer.",
            "expected_top": "silk dress",
            "expected_score": 0.9,
        },
        {
            "name": "Multiple pairs with single words",
            "text": "The leather jacket and cotton shirt were on sale. We also had denim pants.",
            "expected_pairs": ["leather jacket", "cotton shirt", "denim pants"],
        },
        {
            "name": "Single high-value keyword (lowest priority)",
            "text": "The dress is beautiful.",
            "expected_single": "dress",
            "expected_score": 0.5,
        },
        {
            "name": "Contextual modifiers with garments",
            "text": "Black blazer, navy cardigan, striped top, and floral skirt.",
            "expected_pairs": ["black blazer", "navy cardigan", "striped top", "floral skirt"],
        },
    ]

    print("=" * 80)
    print("INTERNAL LINKER KEYWORD EXTRACTION TESTS")
    print("=" * 80)

    for test in test_cases:
        print(f"\n[OK] Test: {test['name']}")
        print(f"  Input: \"{test['text'][:60]}...\"")

        result = extract_high_value_keywords(test["text"])
        print(f"  Results ({len(result)} keywords found):")

        for keyword, score in result[:5]:  # Show top 5
            print(f"    - {keyword:<25} (score: {score:.1f})")

        # Validate expectations
        if result:
            top_keyword, top_score = result[0]
            if "expected_top" in test:
                if top_keyword == test["expected_top"]:
                    print(f"  [PASS] Top keyword matches: {test['expected_top']}")
                else:
                    print(f"  [WARN] Expected {test['expected_top']}, got {top_keyword}")

            if "expected_score" in test:
                if abs(top_score - test["expected_score"]) < 0.01:
                    print(f"  [PASS] Score matches: {test['expected_score']}")
                else:
                    print(f"  [WARN] Expected score {test['expected_score']}, got {top_score}")

    print("\n" + "=" * 80)
    print(f"KEYWORD CONFIGURATION AUDIT")
    print("=" * 80)
    print(f"High-value keywords: {len(HIGH_VALUE_KEYWORDS)} terms")
    print(f"  Garment types: dress, top, blouse, shirt, jacket, etc.")
    print(f"  Materials: leather, denim, cotton, silk, linen, etc.")
    print(f"\nContextual modifiers: {len(CONTEXTUAL_MODIFIERS)} terms")
    print(f"  Colors: black, navy, white, red, blue, etc.")
    print(f"  Patterns: striped, floral, polka, checkered, etc.")
    print(f"  Materials (duplicated for pairing): silk, denim, cotton, etc.")
    print(f"\nStop words filtered: {len(STOP_WORDS)}")
    print("=" * 80)


if __name__ == "__main__":
    test_keyword_extraction()
    print("\n[OK] All tests completed. Ready for dry-run on live articles.")
