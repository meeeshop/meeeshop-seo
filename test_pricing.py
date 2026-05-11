#!/usr/bin/env python3
"""
Test and validate pricing logic without requiring Shopify credentials.
Run: python test_pricing.py
"""

import sys
from price_update import calculate_target_price, COST_MULTIPLIER_MIN, COST_MULTIPLIER_MAX, SHIPPING_COST_MAX, TARGET_PROFIT


def test_pricing():
    """Test pricing logic with various cost points."""
    test_cases = [
        (10, "Budget item"),
        (15, "Small item"),
        (20, "Medium item"),
        (30, "Standard item"),
        (50, "Higher-cost item"),
        (75, "Premium item"),
        (100, "High-end item"),
    ]

    print(f"[Test] Pricing Engine Validation")
    print(f"Configuration:")
    print(f"  Multiplier: {COST_MULTIPLIER_MIN}x - {COST_MULTIPLIER_MAX}x cost")
    print(f"  Shipping: ${SHIPPING_COST_MAX} (avg)")
    print(f"  Target profit: ${TARGET_PROFIT} minimum\n")
    print(f"{'Cost':<8} | {'Category':<20} | {'Final Price':<12} | {'Profit':<10}")
    print("-" * 60)

    all_pass = True
    for cost, category in test_cases:
        price = calculate_target_price(cost, multiplier=None, verbose=False)
        profit = price - cost - (SHIPPING_COST_MAX / 2)
        status = "PASS" if profit >= TARGET_PROFIT else "FAIL"

        if profit < TARGET_PROFIT:
            all_pass = False

        print(f"${cost:<7.2f} | {category:<20} | ${price:<11.2f} | ${profit:<9.2f} {status}")

    print("-" * 60)
    if all_pass:
        print("[PASS] All items meet profit target of ${}\n".format(TARGET_PROFIT))
    else:
        print("[WARN] Some items below profit target!\n")

    # Test psychology pricing (.99 endings)
    print("Testing .99 psychology pricing:")
    test_raw_prices = [45.50, 70.99, 76.99, 80.25, 99.99]
    for raw in test_raw_prices:
        integer = int(raw)
        price_99 = integer + 0.99
        if price_99 < raw:
            price_99 = (integer + 1) + 0.99
        print(f"  ${raw:7.2f} -> ${price_99:7.2f}")

    print("\n[Test] Complete!")


if __name__ == "__main__":
    try:
        test_pricing()
    except Exception as e:
        print(f"[Error] {e}", file=sys.stderr)
        sys.exit(1)
