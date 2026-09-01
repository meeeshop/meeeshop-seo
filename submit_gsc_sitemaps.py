import sys, os, json, requests, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, 'scripts')
from secrets_manager import get_secret

sa_json_str = get_secret('GOOGLE_SA_KEY_JSON')
sa_info = json.loads(sa_json_str)
client_email = sa_info.get('client_email')

print(f'Service Account Email: {client_email}')

try:
    from google.oauth2 import service_account
    import googleapiclient.discovery
    SCOPES = ['https://www.googleapis.com/auth/webmasters']
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    service = googleapiclient.discovery.build('searchconsole', 'v1', credentials=creds)

    site_url = 'https://us.meeeshop.com/'

    sitemaps_to_submit = [
        'https://us.meeeshop.com/sitemap.xml',
        'https://us.meeeshop.com/sitemap_products_1.xml',
        'https://us.meeeshop.com/sitemap_collections_1.xml',
        'https://us.meeeshop.com/sitemap_blogs_1.xml',
        'https://us.meeeshop.com/sitemap_pages_1.xml'
    ]

    print('\n=== 1. SUBMITTING SITEMAPS TO GOOGLE SEARCH CONSOLE API ===')
    for sm in sitemaps_to_submit:
        try:
            service.sitemaps().submit(siteUrl=site_url, feedpath=sm).execute()
            print(f'  ✓ Submitted sitemap to GSC: {sm}')
        except Exception as e:
            if '403' in str(e) or 'permission' in str(e).lower():
                print(f'  ⚠️ Permission Error for {sm}:')
                print(f'     Service Account {client_email} needs to be added as an Owner/Full User in Google Search Console.')
            else:
                print(f'  ⚠️ Error submitting {sm} to GSC: {e}')

except Exception as e:
    print('GSC Setup Exception:', e)

print('\n=== 2. SUBMITTING INDEXNOW PING TO BING/YANDEX ===')
indexnow_key = get_secret('INDEXNOW_KEY')
indexnow_payload = {
    'host': 'us.meeeshop.com',
    'key': indexnow_key,
    'keyLocation': f'https://us.meeeshop.com/{indexnow_key}.txt',
    'urlList': [
        'https://us.meeeshop.com/',
        'https://us.meeeshop.com/collections/womens-dresses',
        'https://us.meeeshop.com/collections/womens-new-collection',
        'https://us.meeeshop.com/blogs/dresses-style-guide'
    ]
}

try:
    r_in = requests.post('https://api.indexnow.org/indexnow', json=indexnow_payload, headers={'Content-Type': 'application/json; charset=utf-8'})
    print('  IndexNow API Status:', r_in.status_code)
    if r_in.status_code in [200, 202]:
        print('  ✓ IndexNow ping successful!')
    else:
        print('  IndexNow response:', r_in.text)
except Exception as e:
    print('  ⚠️ IndexNow ping failed:', e)
