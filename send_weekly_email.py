import os
import sys
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
import re

# Use your existing secrets manager to load decrypted variables natively
from secrets_manager import get_secret

try:
    # Load Shopify configurations safely handling domain URLs
    SHOPIFY_STORE_URL = get_secret('SHOPIFY_STORE_URL')
    STORE_DOMAIN = SHOPIFY_STORE_URL.replace("https://", "").replace("http://", "").strip("/")
    SHOPIFY_ACCESS_TOKEN = get_secret('SHOPIFY_ACCESS_TOKEN')
    
    # Load SMTP configurations
    SMTP_SERVER = get_secret('SMTP_SERVER')
    SMTP_PORT = int(get_secret('SMTP_PORT'))
    SMTP_USER = get_secret('SMTP_USER')
    SMTP_PASS = get_secret('SMTP_PASS')
    FROM_EMAIL = get_secret('FROM_EMAIL')
except Exception as e:
    print(f"❌ Failed to load credentials from secrets.enc: {e}")
    sys.exit(1)

API_VERSION = "2024-01"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN}

last_week_iso = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

def get_new_products():
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?created_at_min={last_week_iso}&status=active"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json().get('products', [])

def get_new_articles():
    """Fetch blog articles published in the last 7 days."""
    all_articles = []
    
    # 1. Fetch all blogs
    blogs_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/blogs.json?limit=250"
    try:
        blogs_response = requests.get(blogs_url, headers=HEADERS)
        blogs_response.raise_for_status()
        blogs = blogs_response.json().get('blogs', [])
    except requests.RequestException as e:
        print(f"⚠️ Could not fetch blogs: {e}")
        return []

    # 2. Fetch recent articles from each blog
    for blog in blogs:
        blog_handle = blog.get('handle')
        articles_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/blogs/{blog['id']}/articles.json?published_at_min={last_week_iso}&status=published"
        try:
            articles_response = requests.get(articles_url, headers=HEADERS)
            articles_response.raise_for_status()
            fetched_articles = articles_response.json().get('articles', [])
            for article in fetched_articles:
                article['blog_handle'] = blog_handle
            all_articles.extend(fetched_articles)
        except requests.RequestException as e:
            print(f"⚠️ Could not fetch articles for blog '{blog.get('title')}': {e}")
            
    return all_articles

def get_customers():
    customers = []
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers.json?limit=250&accepts_marketing=true"
    
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        customers.extend(response.json().get('customers', []))
        
        link_header = response.headers.get("Link", "")
        url = None
        for link in link_header.split(","):
            if 'rel="next"' in link:
                url = link[link.find("<")+1:link.find(">")]
                break
    return customers

def build_html_template(products, articles):
    # --- 1. Selection Logic ---
    hero_product = products[0] if products else None
    
    secondary_products = []
    if len(products) > 1:
        seen_types = set()
        if hero_product and hero_product.get('product_type'):
            seen_types.add(hero_product.get('product_type'))
            
        for p in products[1:]:
            ptype = p.get('product_type')
            if ptype not in seen_types or not ptype:
                secondary_products.append(p)
                if ptype:
                    seen_types.add(ptype)
            if len(secondary_products) >= 4:
                break
        
        # Fill up to 4 if we don't have enough diverse types
        if len(secondary_products) < 4:
            for p in products[1:]:
                if p not in secondary_products and p != hero_product:
                    secondary_products.append(p)
                if len(secondary_products) >= 4:
                    break

    recent_articles = articles[:3] # Limit to latest 3 blogs

    # --- 2. HTML Building ---
    html = """
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; padding: 30px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
            <h1 style="text-align: center; margin-top: 0; font-size: 28px; font-weight: 800; letter-spacing: 1px;"><a href="https://{STORE_DOMAIN}" style="color: #000000; text-decoration: none;">MeeeShop</a></h1>
            <p style="text-align: center; color: #777; font-size: 14px; margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 20px;">Your Weekly Style Update</p>
    """
    
    if hero_product:
        title = hero_product.get('title')
        link = f"https://{STORE_DOMAIN}/products/{hero_product.get('handle')}"
        img_src = hero_product['images'][0].get('src') if hero_product.get('images') else ""
        price = hero_product.get('variants', [{}])[0].get('price', '') if hero_product.get('variants') else ''
        price_text = f"${price}" if price else ""
        
        html += f"""
            <!-- Hero Section -->
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 30px;">
                <tr>
                    <td align="center">
                        <a href="{link}"><img src="{img_src}" alt="{title}" style="width: 100%; max-width: 540px; height: auto; border-radius: 8px; object-fit: cover; max-height: 400px;"/></a>
                        <h2 style="margin: 20px 0 10px; font-size: 24px; color: #333; line-height: 1.2;">{title}</h2>
                        <p style="font-size: 18px; color: #666; margin: 0 0 20px;">{price_text}</p>
                        <a href="{link}" style="display: inline-block; background-color: #ff6b81; color: #ffffff; padding: 14px 30px; text-decoration: none; border-radius: 6px; font-size: 16px; font-weight: bold;">Shop Now</a>
                    </td>
                </tr>
            </table>
        """

    if secondary_products:
        html += """
            <!-- Product Row Grid -->
            <h3 style="color: #333; text-align: center; font-size: 18px; margin-top: 10px; margin-bottom: 20px;">More Fresh Finds</h3>
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 30px;">
                <tr>
        """
        col_width = int(100 / len(secondary_products))
        for p in secondary_products:
            title = p.get('title')
            link = f"https://{STORE_DOMAIN}/products/{p.get('handle')}"
            img_src = p['images'][0].get('src') if p.get('images') else ""
            
            html += f"""
                    <td width="{col_width}%" align="center" valign="top" style="padding: 0 5px;">
                        <a href="{link}"><img src="{img_src}" alt="{title}" style="width: 100%; max-width: 120px; height: auto; border-radius: 6px;"/></a>
                        <p style="font-size: 12px; margin: 10px 0 5px; color: #333; line-height: 1.3; height: 3.9em; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;">{title}</p>
                        <a href="{link}" style="display: inline-block; font-size: 12px; color: #ff6b81; text-decoration: none; font-weight: bold;">Shop Now &rarr;</a>
                    </td>
            """
        html += """
                </tr>
            </table>
        """

    if recent_articles:
        html += '<h3 style="color: #333; text-align: center; font-size: 18px; margin-bottom: 20px;">Latest Style Guides</h3>'
        html += '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
        for a in recent_articles:
            title = a.get('title')
            blog_handle = a.get('blog_handle', 'journal')
            link = f"https://{STORE_DOMAIN}/blogs/{blog_handle}/{a.get('handle')}"
            img_src = a.get('image', {}).get('src') if a.get('image') else ""
            
            excerpt = ""
            if a.get('summary_html'):
                excerpt = re.sub('<[^<]+?>', '', a['summary_html'])
            elif a.get('body_html'):
                excerpt = (re.sub('<[^<]+?>', '', a['body_html']))[:120] + '...'
            
            html += f"""
                <tr>
                    <td width="100" style="padding-bottom: 25px; vertical-align: top;">
                        <a href="{link}"><img src="{img_src}" alt="{title}" style="width: 90px; height: 90px; object-fit: cover; border-radius: 6px; background-color: #f0f0f0;"></a>
                    </td>
                    <td style="padding-bottom: 25px; padding-left: 15px; vertical-align: top;">
                        <a href="{link}" style="color: #333; text-decoration: none; font-weight: bold; font-size: 16px; display: block; margin-bottom: 5px;">{title}</a>
                        <p style="font-size: 13px; color: #666; margin: 0 0 8px; line-height: 1.4;">{excerpt}</p>
                        <a href="{link}" style="color: #ff6b81; text-decoration: none; font-size: 13px; font-weight: bold; display: inline-block;">Read More &rarr;</a>
                    </td>
                </tr>
            """
        html += "</table>"
        
    html += """
        </div>
        <p style="text-align: center; font-size: 12px; color: #999; margin-top: 20px;">
            You are receiving this email because you subscribed to updates from MeeeShop.<br>
            <a href="#" style="color: #999; text-decoration: underline;">Unsubscribe</a>
        </p>
    </body>
    </html>
    """
    return html

def send_email(to_email, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Your Weekly Digest: New Arrivals & Style Guides from MeeeShop"
    msg['From'] = formataddr(("MeeeShop", FROM_EMAIL))
    msg['To'] = to_email
    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

if __name__ == "__main__":
    print("Checking for new products and blogs from the last 7 days...")
    recent_products = get_new_products()
    recent_articles = get_new_articles()
    
    if not recent_products and not recent_articles:
        print("No new products or articles this week. Skipping email.")
        sys.exit(0)
        
    print(f"Found {len(recent_products)} new products and {len(recent_articles)} new articles.")
    
    html_content = build_html_template(recent_products, recent_articles)
    test_email = os.environ.get('TEST_EMAIL')
    is_dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    
    batch_size_str = os.environ.get('BATCH_SIZE', '0')
    batch_size = int(batch_size_str if batch_size_str and batch_size_str.strip() else 0)
    
    batch_index_str = os.environ.get('BATCH_INDEX', '0')
    batch_index = int(batch_index_str if batch_index_str and batch_index_str.strip() else 0)
    
    if test_email:
        print(f"🛠️ TEST MODE: Sending single email to {test_email}")
        send_email(test_email, html_content)
        print("✅ Test email sent!")
    else:
        print(f"{'🏜️ DRY RUN MODE' if is_dry_run else 'Production Mode'}: Fetching customers...")
        all_customers = get_customers()
        total_customers = len(all_customers)
        
        if batch_size > 0:
            start = batch_index * batch_size
            end = start + batch_size
            customers = all_customers[start:end]
            print(f"📦 BATCH MODE: Processing slice [{start}:{end}] — {len(customers)} of {total_customers} customers")
        else:
            customers = all_customers
            
        print(f"Found {len(customers)} marketing subscribers in this run.")
        
        if is_dry_run:
            print("No emails will be sent.")
            for i, customer in enumerate(customers, 1):
                email = customer.get('email')
                if email:
                    print(f"  {i}. Would send to: {email}")
                else:
                    print(f"  {i}. Warning: Customer found without email (ID: {customer.get('id')})")
            print("\n✅ Dry run complete. No emails were sent.")
        else:
            print("Sending emails...")
            sent_count = 0
            for customer in customers:
                email = customer.get('email')
                if email:
                    try:
                        send_email(email, html_content)
                        print(f"  Sent to {email}")
                        sent_count += 1
                    except Exception as e:
                        print(f"  Failed to send to {email}: {e}")
            print(f"\n✅ Production run complete. Successfully sent {sent_count} emails.")