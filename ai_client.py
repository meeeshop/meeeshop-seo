"""
ai_client.py — Free AI provider with automatic fallback
Primary   : Gemini 2.0 Flash  (Google AI Studio — 1M tokens/day, free)
Secondary : Groq Llama-3.3-70B (groq.com — ~500K tokens/day, free)
Tertiary  : OpenRouter Qwen-3-235B :free  (openrouter.ai — free tier)
Fallback  : returns None → caller uses hardcoded template
"""

import os, time, requests
from pathlib import Path


def _load_env():
    for candidate in [Path(__file__).with_name(".env"), Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()

GEMINI_KEY     = os.getenv("GEMINI_API_KEY", "")
GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

_GEMINI_URL      = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
_GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
_OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"


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


def _call_openrouter(prompt: str, max_tokens: int, temperature: float) -> str:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    r = requests.post(
        _OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://us.meeeshop.com",
            "X-Title": "MeeeShop",
        },
        json={
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=45,
    )
    if r.status_code == 429:
        raise RuntimeError("rate-limited")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


_PROVIDERS = [
    ("Gemini",     _call_gemini),
    ("Groq",       _call_groq),
    ("OpenRouter", _call_openrouter),
]


def generate(prompt: str, max_tokens: int = 400, temperature: float = 0.8) -> str | None:
    """
    Try Gemini → Groq → OpenRouter.
    Returns text on first success, None if all fail.
    Callers must always have a hardcoded fallback.
    """
    for name, fn in _PROVIDERS:
        try:
            text = fn(prompt, max_tokens, temperature)
            if text:
                print(f"  [AI:{name}] OK")
                return text
        except Exception as e:
            print(f"  [AI:{name}] {e} — trying next…")
            time.sleep(0.5)
    print("  [AI] all providers failed — using fallback")
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
    print("Testing AI providers…\n")
    for p, s in test_providers().items():
        print(f"  {p:<14}: {s}")
