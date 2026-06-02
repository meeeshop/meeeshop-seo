with open('seo_daily.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('get_secret("BRAND", "MeeeShop")', '"MeeeShop"')
c = c.replace('get_secret("FROM_EMAIL", "support@meeeshop.com")', '"support@meeeshop.com"')
with open('seo_daily.py', 'w', encoding='utf-8') as f:
    f.write(c)
