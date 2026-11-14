#!/usr/bin/env python3
"""
category_metafields_summary.py — Generate GitHub Actions Step Summary
for Category Metafields & Collection SEO Automation.
"""

import os
import sys
import json
from pathlib import Path


def write_summary(batch_label: str = ""):
    summary_path = Path("category_metafields_summary.json")
    if not summary_path.exists():
        print("[Summary] No category_metafields_summary.json found, skipping.")
        return

    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        action = data.get("action", "apply").upper()
        mode = data.get("mode", "daily").upper()
        scope = data.get("scope", "both").upper()
        batch_idx = data.get("batch_index", 0)
        
        prods_fetched = data.get("products_fetched", 0)
        prods_processed = data.get("products_processed", 0)
        prods_updated = data.get("products_updated", 0)
        
        col_stats = data.get("collection_stats", {})
        total_cols = col_stats.get("total_collections", 0)
        updated_cols = col_stats.get("updated_collections", 0)
        skipped_cols = col_stats.get("skipped_collections", 0)
        
        metafields_by_type = data.get("metafields_by_type", {})
        title_suffix = f" (Batch {batch_idx})" if batch_label or batch_idx > 0 else ""

        lines = [
            f"## 🛍️ MeeeShop Category Metafields & Collection SEO Summary{title_suffix}\n",
            f"**Execution Configuration:** Mode: `{mode}` | Action: `{action}` | Scope: `{scope}` | Target: `US Women Shoppers`\n",
            "### 📦 Product Metafields Overview",
            "| Metric | Count |",
            "|---|---|",
            f"| Products Evaluated | **{prods_fetched}** |",
            f"| Products Processed | **{prods_processed}** |",
            f"| Products with Metafields Added/Updated | **{prods_updated}** |\n",
        ]

        if metafields_by_type:
            lines.extend([
                "### 🏷️ Metafields Added by Taxonomy Type",
                "| Metafield Key | Injected Updates |",
                "|---|---|"
            ])
            for k, count in sorted(metafields_by_type.items(), key=lambda x: -x[1]):
                lines.append(f"| `{k}` | **{count}** |")
            lines.append("")

        if total_cols > 0 or updated_cols > 0:
            lines.extend([
                "### 📑 Collection SEO & PAA Accordions Overview",
                "| Metric | Count |",
                "|---|---|",
                f"| Active Store Collections Scanned | **{total_cols}** |",
                f"| Collections Live Updated (SEO + PAA FAQ) | **{updated_cols}** |",
                f"| Collections Preserved (60-Day SERP Stability Lock) | **{skipped_cols}** |\n"
            ])

        summary_text = "\n".join(lines)
        print(summary_text)

        step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary_path:
            with open(step_summary_path, "a", encoding="utf-8") as f:
                f.write(summary_text + "\n")
            print("[Summary] Successfully appended summary to GITHUB_STEP_SUMMARY.")
    except Exception as e:
        print(f"[Summary] Error generating summary: {e}", file=sys.stderr)


if __name__ == "__main__":
    batch = sys.argv[1] if len(sys.argv) > 1 else ""
    write_summary(batch)
