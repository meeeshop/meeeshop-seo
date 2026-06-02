import os
import glob

for filepath in glob.glob('**/*.py', recursive=True):
    if 'fix_hardcodes.py' in filepath or 'secrets_manager.py' in filepath:
        continue
    with open(filepath, 'r', encoding='utf-8') as f:
        c = f.read()
    orig = c
    if ('us.meeeshop.com' in c or 'MeeeShop' in c or 'support@meeeshop.com' in c) and 'get_secret' not in c:
        if 'import os' in c:
            c = c.replace('import os', 'import os\nfrom secrets_manager import get_secret')
        else:
            c = 'from secrets_manager import get_secret\n' + c
    c = c.replace('"us.meeeshop.com"', 'get_secret("SHOPIFY_STORE", "us.meeeshop.com")')
    c = c.replace('"https://us.meeeshop.com"', 'get_secret("SHOPIFY_SITE_URL", "https://us.meeeshop.com")')
    c = c.replace('"support@meeeshop.com"', 'get_secret("FROM_EMAIL", "support@meeeshop.com")')
    c = c.replace('"MeeeShop"', 'get_secret("BRAND", "MeeeShop")')
    if c != orig:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(c)
        print('Updated ' + filepath)
