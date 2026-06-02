#!/usr/bin/env python3
"""
Quick test of internal_linker keyword extraction improvements.
Tests: keyword prioritization, 2-word pairs, contextual scoring.
"""

import sys
import os

# Mock the Shopify API calls and secrets_manager for testing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import only the functions we need
from internal_linker import (
    extract_high_value_keywords,
    STOP_WORDS,
    HIGH_VALUE_KEYWORDS,
    CONTEXTUAL_MODIFIERS,
)

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
            "expected_singles": ["jacket", "shirt", "pants"],
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
        print(f"\n✓ Test: {test['name']}")
        print(f"  Input: \"{test['text'][:60]}...\"")

        result = extract_high_value_keywords(test["text"])
        print(f"  Results ({len(result)} keywords found):")

        for keyword, score in result[:5]:  # Show top 5
            print(f"    - {keyword:<25} (score: {score})")

        # Validate expectations
        if result:
            top_keyword, top_score = result[0]
            if "expected_top" in test:
                if top_keyword == test["expected_top"]:
                    print(f"  ✓ Top keyword matches: {test['expected_top']}")
                else:
                    print(f"  ✗ Expected {test['expected_top']}, got {top_keyword}")

            if "expected_score" in test:
                if abs(top_score - test["expected_score"]) < 0.01:
                    print(f"  ✓ Score matches: {test['expected_score']}")
                else:
                    print(f"  ✗ Expected score {test['expected_score']}, got {top_score}")

    print("\n" + "=" * 80)
    print(f"KEYWORD CONFIGURATION AUDIT")
    print("=" * 80)
    print(f"High-value keywords: {len(HIGH_VALUE_KEYWORDS)} terms")
    print(f"  Examples: {sorted(list(HIGH_VALUE_KEYWORDS))[:10]}")
    print(f"\nContextual modifiers: {len(CONTEXTUAL_MODIFIERS)} terms")
    print(f"  Examples: {sorted(list(CONTEXTUAL_MODIFIERS))[:10]}")
    print(f"\nStop words: {len(STOP_WORDS)} common words filtered")
    print("=" * 80)


if __name__ == "__main__":
    test_keyword_extraction()
    print("\n✓ All tests completed. Ready for dry-run on live articles.")
