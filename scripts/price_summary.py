"""
Generate GitHub Actions step summary from price_update_log.json.
"""

import os
import sys
import json
from pathlib import Path


def write_summary(batch_label: str = ""):
    log_path = Path("price_update_log.json")
    if not log_path.exists():
        print("[Summary] No price_update_log.json found, skipping.")
        return

    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        if not data or not isinstance(data, list):
            print("[Summary] price_update_log.json is empty or invalid format.")
            return

        last_entry = data[-1]
        summary = last_entry.get("summary", {})
        title_suffix = f" ({batch_label})" if batch_label else ""

        lines = [
            f"## MeeeShop Price & Profit Margin Protection Summary{title_suffix}\n",
            "| Metric | Count |",
            "|---|---|",
            f"| Total Products Evaluated | **{summary.get('total_in_batch', summary.get('total', 0))}** |",
            f"| Variants Updated | **{summary.get('updated', 0)}** |",
            f"| Premium Identified | **{summary.get('premium_identified', 0)}** |",
            f"| Tagged Excluded from Shop App | **{summary.get('tagged_excluded', 0)}** |",
            f"| Skipped (Already Optimal) | **{summary.get('skipped', 0)}** |",
            f"| Errors | **{summary.get('errors', 0)}** |\n",
        ]

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
