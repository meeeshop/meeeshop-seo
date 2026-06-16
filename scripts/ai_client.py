"""
ai_client.py — Free AI provider with intelligent fallback
Primary   : Gemini 2.0 Flash  (Google AI Studio — 1M tokens/day, free)
Secondary : Groq Llama-3.3-70B (groq.com — ~500K tokens/day, free)
Tertiary  : OpenRouter free models with auto-fallback
"""

import os
import sys
import time
import requests
from pathlib import Path
from typing import List, Optional


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

GEMINI_KEY = get_secret("GEMINI_API_KEY")
GROQ_KEY = get_secret("GROQ_API_KEY")
OPENROUTER_KEY = get_secret("OPENROUTER_API_KEY")

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_OPENROUTER_FREE_MODELS = [
    "openrouter/free",
]

_OPENROUTER_MODEL_CATEGORIES = {
    "pricing": [
        "openrouter/free",
    ],
    "general": _OPENROUTER_FREE_MODELS,
}


def _get_openrouter_models(category: Optional[str] = None) -> List[str]:
    if category and category in _OPENROUTER_MODEL_CATEGORIES:
        return _OPENROUTER_MODEL_CATEGORIES[category]
    return _OPENROUTER_FREE_MODELS


def _call_gemini(prompt: str, max_tokens: int, temperature: float) -> str:
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    r = requests.post(
        _GEMINI_URL,
        params={"key": GEMINI_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        },
        timeout=30,
    )
    if r.status_code == 429:
        raise RuntimeError("rate-limited")
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(prompt: str, max_tokens: int, temperature: float) -> str:
    if not GROQ_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    r = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=30,
    )
    if r.status_code == 429:
        raise RuntimeError("rate-limited")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_openrouter(prompt: str, max_tokens: int, temperature: float, category: Optional[str] = None) -> str:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    models = _get_openrouter_models(category)
    attempt_logs: List[str] = []

    for model in models:
        try:
            print(f"    [OpenRouter] Trying model: {model}...", flush=True)
            r = requests.post(
                _OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://us.meeeshop.com",
                    "X-Title": "MeeeShop",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=45,
            )

            if r.status_code == 429:
                print(f"      [OpenRouter] {model}: rate-limited (HTTP 429)", flush=True)
                attempt_logs.append(f"{model}: rate-limited (HTTP 429)")
                continue

            if r.status_code >= 400:
                try:
                    err_json = r.json()
                    err_msg = str(err_json.get("error", ""))
                except Exception:
                    err_msg = r.text

                if "context_length_exceeded" in err_msg.lower() or "token" in err_msg.lower():
                    print(f"      [OpenRouter] {model}: token limit - {err_msg[:120]}", flush=True)
                    attempt_logs.append(f"{model}: token limit - {err_msg}")
                    continue

                print(f"      [OpenRouter] {model}: error {r.status_code} - {err_msg[:120]}", flush=True)
                attempt_logs.append(f"{model}: error {r.status_code} - {err_msg}")
                continue

            print(f"      [OpenRouter] {model}: success", flush=True)
            attempt_logs.append(f"{model}: OK")
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"      [OpenRouter] {model}: exception - {e}", flush=True)
            attempt_logs.append(f"{model}: exception - {e}")
            continue

    log_blob = " | ".join(attempt_logs) if attempt_logs else "no attempts"
    raise RuntimeError(f"All OpenRouter models failed: {log_blob}")


_PROVIDERS = [
    ("Gemini", _call_gemini),
    ("Groq", _call_groq),
    ("OpenRouter", lambda p, m, t: _call_openrouter(p, m, t, None)),
]


def generate(prompt: str, max_tokens: int = 400, temperature: float = 0.8, category: str = None) -> str | None:
    """Try Gemini → Groq → OpenRouter. Returns text on first success, None if all fail."""
    if category == "pricing":
        try:
            text = _call_openrouter(prompt, max_tokens, temperature, category="pricing")
            if text:
                print(f"  [AI:OpenRouter-Pricing] OK")
                return text
        except Exception as e:
            print(f"  [AI:OpenRouter-Pricing] {e} - falling back...")

    for name, fn in _PROVIDERS:
        try:
            if category == "pricing":
                text = _call_openrouter(prompt, max_tokens, temperature, category="pricing")
            else:
                text = fn(prompt, max_tokens, temperature)
            if text:
                print(f"  [AI:{name}] OK")
                return text
        except Exception as e:
            print(f"  [AI:{name}] {e} - trying next...")

    print("  [AI] all providers failed - returning None")
    return None


def test_providers() -> dict:
    results = {}
    probe = "Reply with the single word: ok"
    for name, fn in _PROVIDERS:
        try:
            r = fn(probe, 10, 0.1)
            results[name] = "OK  " + (r[:40] if r else "(empty)")
        except Exception as e:
            results[name] = f"FAIL {e}"
    return results


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("Testing AI providers...\n")
    for p, s in test_providers().items():
        safe_s = s.encode("ascii", errors="replace").decode("ascii")
        print(f"  {p:<14}: {safe_s}")
