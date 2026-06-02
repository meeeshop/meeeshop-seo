from secrets_manager import get_secret
import json
from cryptography.fernet import Fernet
from secrets_manager import _get_keys, _double_decrypt

primary, fallback = _get_keys()
fp = Fernet(primary)
ff = Fernet(fallback)

def enc(val):
    return fp.encrypt(ff.encrypt(val.encode())).decode()

vault = {
    'SHOPIFY_STORE_URL': enc('https://us.meeeshop.com'),
    'SHOPIFY_SITE_URL': enc('https://us.meeeshop.com'),
    'SHOPIFY_ACCESS_TOKEN': enc('shpat_1234567890abcdef1234567890abcdef'),
    'SMTP_SERVER': enc('smtp.gmail.com'),
    'SMTP_PORT': enc('587'),
    'SMTP_USER': enc('test@gmail.com'),
    'SMTP_PASS': enc('password123'),
    'FROM_EMAIL': enc('support@meeeshop.com'),
    'SHOPIFY_STORE': enc('us-meeeshop.myshopify.com'),
    'BRAND': enc('MeeeShop'),
}

with open('secrets.enc', 'w') as f:
    json.dump(vault, f, indent=2)

print('Secrets encrypted successfully.')
