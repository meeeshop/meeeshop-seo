with open('seo_daily.py', 'r', encoding='utf-8') as f:
    c = f.read()

old = 'JSONLD_SNIPPET = r""""{% comment %}'
new = 'BRAND_SECRET = get_secret("BRAND", "MeeeShop")\\nEMAIL_SECRET = get_secret("FROM_EMAIL", "support@meeeshop.com")\\nJSONLD_SNIPPET = r""""{% comment %}'

c = c.replace(old, new)

c = c.replace('"MeeeShop"', '" + BRAND_SECRET + r"')
c = c.replace('"support@meeeshop.com"', '" + EMAIL_SECRET + r"')
c = c.replace('"us.meeeshop"', '" + get_secret("DISPLAY_BRAND", "us.meeeshop") + r"')
with open('seo_daily.py', 'w', encoding='utf-8') as f:
    f.write(c)
