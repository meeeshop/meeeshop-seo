with open('internal_linker.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('default=get_secret("SHOPIFY_SITE_URL", "https://us.meeeshop.com")', '"https://us.meeeshop.com"')
with open('internal_linker.py', 'w', encoding='utf-8') as f:
    f.write(c)
