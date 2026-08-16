#!/usr/bin/env python3
"""
paa_pasf_seo_engine.py — Unified PAA & PASF Optimization Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unified engine that handles free Google PAA/PASF extraction, AI content generation with
multi-provider fallback (Gemini -> Groq -> OpenRouter), rule-based fallback when rate limited,
and 60-day update locks to prevent content churn.
"""

import os
import sys
import re
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOG_FILE = REPO_ROOT / "category_metafields_log.json"

sys.path.insert(0, str(SCRIPT_DIR))
from google_question_fetcher import GoogleQuestionFetcher
import ai_client
import fallback_template_engine as fallback_engine

# Initialize Google fetcher
fetcher = GoogleQuestionFetcher()

# 60-day TTL in seconds (60 * 86400)
STABILITY_LOCK_TTL_SECONDS = 60 * 86400


def is_recently_updated(entity_key: str, log_path: Path = LOG_FILE) -> bool:
    """Checks if an entity (collection handle or product ID) was updated in the last 60 days."""
    if not log_path.exists():
        return False
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        entry = data.get(entity_key)
        if not entry:
            return False
            
        ts_str = entry.get("updated_at")
        if not ts_str:
            return False
            
        updated_dt = datetime.fromisoformat(ts_str)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            
        now = datetime.now(timezone.utc)
        elapsed = (now - updated_dt).total_seconds()
        
        if elapsed < STABILITY_LOCK_TTL_SECONDS:
            days_ago = int(elapsed // 86400)
            print(f"  [Stability Lock] '{entity_key}' updated {days_ago} days ago (<60 days) — SKIPPING to preserve SERP index.")
            return True
            
    except Exception as e:
        print(f"  [Warning] Failed checking stability lock for '{entity_key}': {e}")
        
    return False


def log_entity_update(entity_key: str, status: str = "success", log_path: Path = LOG_FILE):
    """Records update timestamp in log file."""
    data = {}
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
            
    data[entity_key] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status
    }
    
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  [Warning] Failed writing update log for '{entity_key}': {e}")


def generate_optimized_collection_seo(entity_name: str, pasf_modifiers: List[str] = None) -> Tuple[str, str]:
    """Generates Meta Title (50-60 chars) and Meta Description (140-155 chars) using PASF modifiers."""
    if not pasf_modifiers:
        pasf_modifiers = fetcher.fetch_pasf_modifiers(entity_name)
    
    # Strictly filter out non-US location terms and competitor retailer names
    pasf_modifiers = [
        m for m in pasf_modifiers 
        if not fetcher.has_non_us_location(m) and not fetcher.has_competitor_retailer(m, allowed_brand=entity_name)
    ]
        
    mod_str = ", ".join(pasf_modifiers[:4])
    prompt = (
        f"You are a Shopify SEO Specialist. Write a Meta Title and Meta Description for a US women's boutique collection: '{entity_name}'.\n"
        f"Target Audience: STRICTLY United States (US) customers only. DO NOT include any non-US country, region, or city names (such as UK, Australia, Canada, NZ, Europe, London, etc.).\n"
        f"DO NOT mention any competitor marketplace or retailer names (such as Amazon, Next, Walmart, Target, Shein, Nordstrom, eBay, etc.) unless it matches the brand/vendor name '{entity_name}'.\n"
        f"Incorporate these popular search modifiers naturally: {mod_str}.\n"
        f"Format requirements:\n"
        f"- Meta Title: 50 to 60 characters, include brand/type and key search term, end with '| MeeeShop'.\n"
        f"- Meta Description: 140 to 155 characters, clear call to action, fast US shipping.\n"
        f"Return JSON ONLY: {{\x22meta_title\x22: \x22...\x22, \x22meta_description\x22: \x22...\x22}}"
    )
    
    # Try AI providers (Gemini -> Groq -> OpenRouter)
    ai_resp = ai_client.generate(prompt, max_tokens=250, temperature=0.6)
    
    if ai_resp:
        try:
            json_match = re.search(r"\{.*\}", ai_resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                title = data.get("meta_title", "").strip()
                desc = data.get("meta_description", "").strip()
                if title and desc:
                    title = fetcher.remove_disallowed_terms(title, allowed_brand=entity_name)
                    desc = fetcher.remove_disallowed_terms(desc, allowed_brand=entity_name)
                    return title[:60], desc[:155]
        except Exception as e:
            print(f"  [AI Parse Warning] Failed parsing AI response for '{entity_name}': {e}")

    # Fallback to rule-based template engine if AI fails or rate limits
    print(f"  [Fallback Engine] Generating deterministic Meta Title/Desc for '{entity_name}'")
    fb_title = fetcher.remove_disallowed_terms(fallback_engine.generate_fallback_meta_title(entity_name, pasf_modifiers), allowed_brand=entity_name)
    fb_desc = fetcher.remove_disallowed_terms(fallback_engine.generate_fallback_meta_description(entity_name, pasf_modifiers), allowed_brand=entity_name)
    return fb_title, fb_desc



def generate_collection_faq_accordion(entity_name: str) -> Tuple[str, Dict]:
    """Extracts live PAA questions for entity and generates HTML Accordion + JSON-LD FAQ Schema."""
    paa_questions = fetcher.fetch_live_google_questions(entity_name, limit=6)
    if not paa_questions:
        paa_questions = [
            f"Is {entity_name} true to size?",
            f"How to style {entity_name} for women?",
            f"How to care for and wash {entity_name}?",
            f"What shoes to wear with {entity_name}?"
        ]
        
    # Generate HTML Accordion
    html_accordion = fallback_engine.generate_fallback_faq_block(entity_name, paa_questions)
    
    # Generate Schema
    faq_schema = fallback_engine.generate_fallback_faq_schema(entity_name, paa_questions)
    
    return html_accordion, faq_schema


if __name__ == "__main__":
    test_entity = "Judy Blue Flare Jeans"
    print(f"\n--- Testing PAA/PASF SEO Engine for '{test_entity}' ---")
    
    mods = fetcher.fetch_pasf_modifiers(test_entity)
    print(f"Extracted PASF Modifiers: {mods}")
    
    title, desc = generate_optimized_collection_seo(test_entity, mods)
    print(f"\nMeta Title ({len(title)} chars): {title}")
    print(f"Meta Desc  ({len(desc)} chars): {desc}")
    
    html_faq, schema_faq = generate_collection_faq_accordion(test_entity)
    print(f"\nGenerated FAQ Accordion length: {len(html_faq)} bytes")
    print(f"Generated FAQ Schema Questions  : {len(schema_faq['mainEntity'])}")
