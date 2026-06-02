with open('secrets_manager.py', 'r', encoding='utf-8') as f:
    c = f.read()
old = 'def get_secret(name: str) -> str:\\n    """Decrypt and return a single secret. Logs caller + timestamp (not the value)."""\\n    global _sanitizer_installed\\n    if not _sanitizer_installed:\\n        _install_sanitizer()\\n        _sanitizer_installed = True\\n\\n    primary, fallback = _get_keys()\\n    vault = _load_vault()\\n    if name not in vault:\\n        raise KeyError'
new = 'def get_secret(name: str, default: str = None) -> str:\\n    """Decrypt and return a single secret. Logs caller + timestamp (not the value)."""\\n    global _sanitizer_installed\\n    if not _sanitizer_installed:\\n        _install_sanitizer()\\n        _sanitizer_installed = True\\n\\n    primary, fallback = _get_keys()\\n    vault = _load_vault()\\n    if name not in vault:\\n        if default is not None:\\n            return default\\n        raise KeyError'
c = c.replace(old, new)
with open('secrets_manager.py', 'w', encoding='utf-8') as f:
    f.write(c)
