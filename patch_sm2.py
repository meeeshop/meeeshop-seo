with open('secrets_manager.py', 'r', encoding='utf-8') as f:
    c = f.read()
old = 'def get_secret(name: str) -> str:'
new = 'def get_secret(name: str, default: str = None) -> str:'
c = c.replace(old, new)
old2 = 'if name not in vault:\\n        raise KeyError'
new2 = 'if name not in vault:\\n        if default is not None:\\n            return default\\n        raise KeyError'
c = c.replace(old2, new2)
with open('secrets_manager.py', 'w', encoding='utf-8') as f:
    f.write(c)
