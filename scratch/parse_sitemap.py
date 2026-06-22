import requests
import xml.etree.ElementTree as ET

url = "https://us.meeeshop.com/sitemap_collections_1.xml?from=279139745963&to=312370397355"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

resp = requests.get(url, headers=headers)
if resp.status_code == 200:
    root = ET.fromstring(resp.content)
    # The XML namespace is usually http://www.sitemaps.org/schemas/sitemap/0.9
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    
    urls = []
    for loc in root.findall('.//ns:loc', namespaces):
        urls.append(loc.text)
        
    print(f"Total collections in sitemap: {len(urls)}")
    for u in urls[:20]:
        print(u)
else:
    print(f"Error fetching sitemap: {resp.status_code}")
    print(resp.text)
