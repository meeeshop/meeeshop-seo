#!/usr/bin/env python3
"""
fallback_template_engine.py — Deterministic Rule-Based Fallback Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Provides high-converting, SEO-optimized templates when AI clients (Gemini, Groq, OpenRouter)
are rate limited (HTTP 429) or unavailable. Ensures 100% workflow execution completion.
"""

import re
import json
from typing import List, Dict, Tuple, Optional
from google_question_fetcher import GoogleQuestionFetcher


def generate_fallback_meta_title(entity_name: str, pasf_modifiers: List[str] = None) -> str:
    """Constructs a 50-60 character Meta Title incorporating entity name and top PASF modifiers."""
    clean_entity = entity_name.title().strip()
    raw_mods = pasf_modifiers or ["Women's", "Fit & Sizing", "Style Guide"]
    mods = [
        m for m in raw_mods 
        if not GoogleQuestionFetcher.has_non_us_location(m) 
        and not GoogleQuestionFetcher.has_competitor_retailer(m, allowed_brand=entity_name)
    ]
    if not mods:
        mods = ["Women's", "Fit & Sizing", "Style Guide"]
    
    # Priority PASF modifiers
    mod_str = " & ".join([m.title() for m in mods[:2]])
    title = f"{clean_entity} for Women: {mod_str} | MeeeShop"
    
    if len(title) > 60:
        title = f"{clean_entity} Women's Style & Sizing Guide | MeeeShop"
    if len(title) > 60:
        title = f"{clean_entity} Collection | MeeeShop"
        
    return GoogleQuestionFetcher.remove_disallowed_terms(title, allowed_brand=entity_name)[:60]


def generate_fallback_meta_description(entity_name: str, pasf_modifiers: List[str] = None) -> str:
    """Constructs a 140-155 character Meta Description incorporating entity name and PASF modifiers."""
    clean_entity = entity_name.title().strip()
    raw_mods = [m.lower() for m in (pasf_modifiers or ["size chart", "prices", "flattering fits"])]
    mods = [
        m for m in raw_mods 
        if not GoogleQuestionFetcher.has_non_us_location(m) 
        and not GoogleQuestionFetcher.has_competitor_retailer(m, allowed_brand=entity_name)
    ]
    if not mods:
        mods = ["size chart", "prices", "flattering fits"]
    
    mod1 = mods[0] if len(mods) > 0 else "size chart"
    mod2 = mods[1] if len(mods) > 1 else "prices"
    
    desc = (
        f"Shop {clean_entity} for women at MeeeShop. Explore our accurate {mod1}, "
        f"compare {mod2}, and discover flattering styles. Fast US shipping & easy returns!"
    )
    
    if len(desc) > 155:
        desc = (
            f"Shop women's {clean_entity} at MeeeShop. Check our {mod1}, "
            f"find your perfect fit, and discover trending outfits. Fast US shipping!"
        )
    return GoogleQuestionFetcher.remove_disallowed_terms(desc, allowed_brand=entity_name)[:155]


def generate_fallback_faq_block(entity_name: str, paa_questions: List[str]) -> str:
    """Generates an HTML FAQ accordion block for collection pages or blog posts."""
    clean_entity = entity_name.title().strip()
    
    html_out = [
        f'<div class="seo-faq-accordion" style="margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">',
        f'  <h2 style="font-size: 1.4rem; margin-bottom: 16px;">Frequently Asked Questions About {clean_entity}</h2>'
    ]
    
    default_answers = {
        "fit": f"{clean_entity} typically runs true to size. For a more relaxed silhouette or layering, we recommend sizing up one size.",
        "quality": f"{clean_entity} is crafted from premium stretch materials designed to hold its shape, offer all-day comfort, and prevent bagging at the knees.",
        "style": f"Pair {clean_entity} with fitted ankle boots or sleek white sneakers for a casual chic everyday outfit.",
        "wash": f"Machine wash cold inside out with like colors. Line dry or tumble dry low to preserve color vibrancy and elasticity.",
        "expensive": f"{clean_entity} offers premium boutique designer quality at an accessible price point, giving you luxury fit without the markup."
    }
    
    for idx, q in enumerate(paa_questions[:4], 1):
        q_clean = q.strip()
        q_lower = q_clean.lower()
        
        # Match answer angle
        ans = default_answers["fit"]
        if "wash" in q_lower or "clean" in q_lower or "care" in q_lower:
            ans = default_answers["wash"]
        elif "good" in q_lower or "quality" in q_lower or "material" in q_lower:
            ans = default_answers["quality"]
        elif "expensive" in q_lower or "price" in q_lower or "worth" in q_lower:
            ans = default_answers["expensive"]
        elif "style" in q_lower or "wear" in q_lower or "shoes" in q_lower:
            ans = default_answers["style"]
            
        html_out.append(f'  <details style="margin-bottom: 12px; border-bottom: 1px solid #f4f4f4; padding-bottom: 8px;">')
        html_out.append(f'    <summary style="font-weight: 600; cursor: pointer; font-size: 1.05rem;">{q_clean}</summary>')
        html_out.append(f'    <p style="margin-top: 8px; font-size: 0.95rem; color: #444; line-height: 1.5;">{ans}</p>')
        html_out.append(f'  </details>')
        
    html_out.append('</div>')
    return "\n".join(html_out)


def generate_fallback_faq_schema(entity_name: str, paa_questions: List[str]) -> Dict:
    """Constructs a valid Schema.org FAQPage JSON-LD dictionary."""
    clean_entity = entity_name.title().strip()
    
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": []
    }
    
    for q in paa_questions[:4]:
        q_clean = q.strip()
        ans = f"{clean_entity} offers flattering fits, premium stretch fabrics, and true-to-size styling. Refer to our detailed size chart for accurate measurements."
        
        schema["mainEntity"].append({
            "@type": "Question",
            "name": q_clean,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": ans
            }
        })
        
    return schema


def generate_fallback_article_body(entity_name: str, main_question: str, paa_questions: List[str]) -> str:
    """Generates a full HTML blog article structure when AI providers are rate limited."""
    clean_entity = entity_name.title().strip()
    
    html = [
        f'<p class="lead">Finding the perfect fit and styling balance with <strong>{clean_entity}</strong> can elevate your everyday boutique wardrobe. In this guide, we address the top real-world fashion questions regarding fit, quality, and pairing.</p>',
        f'<h2 style="font-size: 1.3rem; margin-top: 24px;">{main_question}</h2>',
        f'<p>{clean_entity} is a standout piece for versatile modern styling. Designed with premium stretch retention and flattering cuts, it seamlessly transitions from relaxed daytime errands to elevated evening outfits.</p>',
        f'<h3 style="font-size: 1.1rem; margin-top: 18px;">Key Fit & Styling Highlights:</h3>',
        f'<ul>',
        f'  <li><strong>Flattering Silhouette:</strong> Tailored to contour curves while offering flexible stretch mobility.</li>',
        f'  <li><strong>Versatile Pairing:</strong> Complements ankle boots, casual sneakers, and layered outerwear.</li>',
        f'  <li><strong>Easy Care:</strong> Machine washable with cold water to maintain fabric integrity.</li>',
        f'</ul>',
        generate_fallback_faq_block(clean_entity, paa_questions)
    ]
    
    return "\n".join(html)


if __name__ == "__main__":
    test_title = generate_fallback_meta_title("Risen High Rise Jeans", ["size chart", "women", "price"])
    test_desc = generate_fallback_meta_description("Risen High Rise Jeans", ["size chart", "prices"])
    print("Meta Title Test      :", test_title, f"({len(test_title)} chars)")
    print("Meta Description Test:", test_desc, f"({len(test_desc)} chars)")
