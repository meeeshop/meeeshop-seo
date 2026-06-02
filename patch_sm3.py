import re
with open('secrets_manager.py', 'r', encoding='utf-8') as f:
    c = f.read()
old = r'if name not in vault:\s+raise KeyError'
new = 'if name not in vault:\n        if default is not None:\n            return default\n        raise KeyError'
c = re.sub(old, new, c)
with open('secrets_manager.py', 'w', encoding='utf-8') as f:
    f.write(c)
