#!/usr/bin/env python3
"""
Demo: Show new detailed logging format
Run: python demo_logging.py
"""

import json
from datetime import datetime

print("\n" + "Seq" + " " * 2 + "| " + "Product Title" + " " * 21 + "| " + "Old Price" + " " * 1 + "| " + "New Price" + " " * 1 + "| " + "Cost" + " " * 3 + "| " + "Profit" + " " * 2 + "| " + "Status")
print("-" * 110)

# Demo results
results = {
    "updated": 0,
    "skipped": 0,
    "products": []
}

# Product 1: Summer Dress - Price increase
print("1    | Summer Dress Classic           | $45.00     | $48.99     | $18.00   | $15.49   | UPDATED")
results["updated"] += 1
results["products"].append({
    "sku": "SD-001",
    "title": "Summer Dress Classic",
    "old_price": 45.00,
    "new_price": 48.99,
    "cost": 18.00,
    "profit": 15.49,
    "status": "updated"
})

# Product 2: T-Shirt - Price increase
print("2    | Casual T-Shirt                 | $22.50     | $23.99     | $8.50    | $10.49   | UPDATED")
results["updated"] += 1
results["products"].append({
    "sku": "TS-002",
    "title": "Casual T-Shirt",
    "old_price": 22.50,
    "new_price": 23.99,
    "cost": 8.50,
    "profit": 10.49,
    "status": "updated"
})

# Product 3: Designer Jeans - No cost
print("3    | Designer Jeans                 | —          | —          | —        | —        | NO COST")
results["skipped"] += 1
results["products"].append({
    "sku": "DJ-003",
    "title": "Designer Jeans",
    "old_price": None,
    "new_price": None,
    "cost": None,
    "profit": None,
    "status": "skipped_no_cost"
})

# Product 4: Evening Gown - Already optimal
print("4    | Evening Gown                   | $89.99     | $89.99     | $35.00   | $42.49   | OPTIMAL")
results["skipped"] += 1
results["products"].append({
    "sku": "EG-004",
    "title": "Evening Gown",
    "old_price": 89.99,
    "new_price": 89.99,
    "cost": 35.00,
    "profit": 42.49,
    "status": "skipped_optimal"
})

# Product 5: Casual Blazer - Price increase
print("5    | Casual Blazer                  | $55.00     | $56.99     | $22.00   | $24.49   | UPDATED")
results["updated"] += 1
results["products"].append({
    "sku": "CB-005",
    "title": "Casual Blazer",
    "old_price": 55.00,
    "new_price": 56.99,
    "cost": 22.00,
    "profit": 24.49,
    "status": "updated"
})

print("-" * 110)
print(f"\n[PriceUpdate] Complete: {results['updated']} updated, {results['skipped']} skipped, 0 errors")

# Show JSON log format
print("\n" + "=" * 110)
print("[JSON Log Format] price_update_log.json")
print("=" * 110 + "\n")

log_entry = {
    "timestamp": datetime.now().isoformat(),
    "summary": {
        "total_products": 5,
        "updated": results["updated"],
        "skipped": results["skipped"],
        "errors": 0,
    },
    "products": results["products"]
}

print(json.dumps([log_entry], indent=2))

print("\n" + "=" * 110)
print("\nKey improvements in logging:")
print("  • Detailed product-level tracking: SKU, old price, new price, cost, profit")
print("  • Status tracking: 'updated', 'skipped_optimal', 'skipped_no_cost', 'error'")
print("  • Console display: Easy-to-read table format")
print("  • JSON log: Structured data for analysis and monitoring")
print("=" * 110)
