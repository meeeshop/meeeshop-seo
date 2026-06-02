import os
import sys
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
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

last_week_iso = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"

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
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers.json?accepts_marketing=true"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json().get('customers', [])

def build_html_template(products, articles):
    html = """
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
            <h1 style="color: #ff6b81; text-align: center; border-bottom: 2px solid #f0f0f0; padding-bottom: 15px;">✨ Fresh Arrivals</h1>
    """
    
    if products:
        html += '<h2 style="color: #333; text-align: center; font-size: 20px; margin-top: 20px;">New In The Shop</h2>'
        html += '<table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">'
        for p in products:
            title = p.get('title')
            link = f"https://{STORE_DOMAIN}/products/{p.get('handle')}"
            img_src = p['images'][0].get('src') if p.get('images') else ""
            
            html += f"""
                <tr>
                    <td width="80" style="padding-bottom: 20px;">
                        <a href="{link}"><img src="{img_src}" alt="{title}" style="width: 70px; height: 70px; object-fit: cover; border-radius: 6px; background-color: #f0f0f0;"></a>
                    </td>
                    <td style="padding-bottom: 20px; padding-left: 15px; vertical-align: middle;">
                        <a href="{link}" style="color: #333; text-decoration: none; font-weight: bold; font-size: 16px;">{title}</a>
                        <br>
                        <a href="{link}" style="color: #ff6b81; text-decoration: none; font-size: 14px; margin-top: 6px; display: inline-block;">Shop Now &rarr;</a>
                    </td>
                </tr>
            """
        html += "</table>"

    if articles:
        html += '<h2 style="color: #333; text-align: center; font-size: 20px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 20px;">Latest From The Blog</h2>'
        html += '<table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">'
        for a in articles:
            title = a.get('title')
            blog_handle = a.get('blog_handle', 'journal')
            link = f"https://{STORE_DOMAIN}/blogs/{blog_handle}/{a.get('handle')}"
            img_src = a.get('image', {}).get('src') if a.get('image') else ""
            
            excerpt = ""
            if a.get('summary_html'):
                excerpt = re.sub('<[^<]+?>', '', a['summary_html'])
            elif a.get('body_html'):
                excerpt = (re.sub('<[^<]+?>', '', a['body_html']))[:150] + '...'
            
            html += f"""
                <tr>
                    <td width="80" style="padding-bottom: 20px;">
                        <a href="{link}"><img src="{img_src}" alt="{title}" style="width: 70px; height: 70px; object-fit: cover; border-radius: 6px; background-color: #f0f0f0;"></a>
                    </td>
                    <td style="padding-bottom: 20px; padding-left: 15px; vertical-align: top;">
                        <a href="{link}" style="color: #333; text-decoration: none; font-weight: bold; font-size: 16px;">{title}</a>
                        <p style="font-size: 14px; color: #666; margin-top: 4px; margin-bottom: 6px; line-height: 1.4;">{excerpt}</p>
                        <a href="{link}" style="color: #ff6b81; text-decoration: none; font-size: 14px; display: inline-block;">Read More &rarr;</a>
                    </td>
                </tr>
            """
        html += "</table>"
        
    html += """
        </div>
    </body>
    </html>
    """
    return html

def send_email(to_email, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Your Weekly Digest: New Arrivals & Style Guides from MeeeShop"
    msg['From'] = FROM_EMAIL
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
    
    if test_email:
        print(f"🛠️ TEST MODE: Sending single email to {test_email}")
        send_email(test_email, html_content)
        print("✅ Test email sent!")
    else:
        print("Production Mode: Fetching customers...")
        customers = get_customers()
        print(f"Found {len(customers)} marketing subscribers. Sending emails...")
        for customer in customers:
            email = customer.get('email')
            if email:
                try:
                    send_email(email, html_content)
                    print(f"  Sent to {email}")
                except Exception as e:
                    print(f"  Failed to send to {email}: {e}")