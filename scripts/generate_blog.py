import os
import sys
import json
import time
import random
import requests
import io
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google import genai
from cryptography.fernet import Fernet

# --- Configuration ---
ENCRYPTED_SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.enc")

AI_CLICHES = [
    "In today's fast-paced digital age", "Embark on a journey", "delve into", "take a deep dive",
    "Tapestry", "robust", "multifaceted", "testament", "unlock", "elevate",
    "In conclusion", "it's important to note"
]

def decrypt_secrets(primary_key, fallback_key):
    """
    Decrypts the secrets.enc file using the Double-Fernet strategy.
    """
    if not os.path.exists(ENCRYPTED_SECRETS_FILE):
        print(f"Error: Encrypted file '{ENCRYPTED_SECRETS_FILE}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(ENCRYPTED_SECRETS_FILE, "r") as f:
        encrypted_data = json.load(f)
        
    decrypted_secrets = {}
    
    # We decrypt each value in the JSON
    for key, val in encrypted_data.items():
        try:
            # Double-Fernet Decrypt: Fernet(FALLBACK).decrypt(Fernet(PRIMARY).decrypt(ciphertext))
            inner = Fernet(primary_key).decrypt(val.encode("utf-8"))
            decrypted_val = Fernet(fallback_key).decrypt(inner).decode("utf-8")
            decrypted_secrets[key] = decrypted_val
        except Exception as e:
            print(f"Warning: Failed to decrypt secret '{key}'. Key might be wrong or corrupt.", file=sys.stderr)
            
    return decrypted_secrets

def get_shopify_session(store_url, access_token):
    session = requests.Session()
    session.headers.update({
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    })
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[ 429, 500, 502, 503, 504 ])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def fetch_shopify_data(session, store_url):
    products = []
    collections = []
    try:
        prod_resp = session.get(f"{store_url}/admin/api/2023-10/products.json?status=active&limit=10")
        prod_resp.raise_for_status()
        products_data = prod_resp.json().get('products', [])
        
        featured = random.sample(products_data, min(3, len(products_data)))
            
        for p in featured:
            handle = p.get('handle')
            img_url = p.get('image', {}).get('src') if p.get('image') else None
            products.append({
                "title": p.get('title'),
                "url": f"/products/{handle}",
                "image_url": img_url
            })
            
        coll_resp = session.get(f"{store_url}/admin/api/2023-10/custom_collections.json?limit=5")
        if coll_resp.status_code == 200:
            collections_data = coll_resp.json().get('custom_collections', [])
            for c in collections_data:
                handle = c.get('handle')
                collections.append({
                    "title": c.get('title'),
                    "url": f"/collections/{handle}"
                })
    except Exception as e:
        print(f"Warning: Failed to fetch Shopify data: {e}")
        
    return products, collections

def publish_shopify_article(session, store_url, blog_id, title, html_content, author, image_bytes=None, draft=True):
    url = f"{store_url}/admin/api/2023-10/blogs/{blog_id}/articles.json"
    tags = "AI_Generated, Needs_Review" if draft else ""
    payload = {
        "article": {
            "title": title,
            "author": author,
            "tags": tags,
            "body_html": html_content,
            "published": not draft
        }
    }
    
    if image_bytes:
        import base64
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        payload["article"]["image"] = {
            "attachment": b64_img,
            "alt": f"Illustration for {title}"
        }

    resp = session.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()['article']

def get_shopify_blogs(session, store_url):
    resp = session.get(f"{store_url}/admin/api/2023-10/blogs.json")
    resp.raise_for_status()
    return resp.json().get('blogs', [])

def process_existing_drafts(session, store_url, blog_id):
    url = f"{store_url}/admin/api/2023-10/blogs/{blog_id}/articles.json?limit=50"
    resp = session.get(url)
    if resp.status_code != 200:
        return
        
    articles = resp.json().get('articles', [])
    for article in articles:
        tags = [t.strip() for t in article.get('tags', '').split(',')]
        if 'Approved' in tags and not article.get('published_at'):
            print(f"Publishing approved draft: {article['title']}")
            new_tags = [t for t in tags if t != 'Approved' and t != 'Needs_Review']
            payload = {
                "article": {
                    "id": article['id'],
                    "tags": ", ".join(new_tags),
                    "published": True
                }
            }
            update_url = f"{store_url}/admin/api/2023-10/blogs/{blog_id}/articles/{article['id']}.json"
            session.put(update_url, json=payload)

def get_best_image_model(client):
    try:
        models_iterable = client.models.list()
        # Find 'imagen' models (which are used for image generation)
        available_models = [m.name for m in models_iterable if "imagen" in m.name.lower()]
        
        priority = [
            "imagen-4.0-ultra-generate-001",
            "imagen-4.0-generate-001",
            "imagen-4.0-fast-generate-001",
            "imagen-3.0-generate-001"
        ]
        
        for p in priority:
            for m in available_models:
                if p in m:
                    print(f"Auto-selected image model: {m}")
                    return m.replace('models/', '')
                    
        if available_models:
            return available_models[0].replace('models/', '')
    except Exception as e:
        print(f"Warning: Failed to list image models: {e}")
        
    return 'imagen-4.0-generate-001'

def generate_article_image(client, topic):
    print(f"Generating feature image for topic: '{topic}'...")
    try:
        model_name = get_best_image_model(client)
        image_prompt = (
            f"High quality editorial lifestyle photography for a women's fashion and lifestyle blog. "
            f"Topic: {topic}. "
            f"Vibrant colors, highly detailed, cinematic lighting, 16:9 aspect ratio, suitable for a premium Google Discover banner. "
            f"No text, no watermarks, realistic and relatable."
        )
        response = client.models.generate_images(
            model=model_name,
            prompt=image_prompt,
            config=dict(
                number_of_images=1,
                aspect_ratio='16:9',
                output_mime_type='image/jpeg'
            )
        )
        if response.generated_images:
            return response.generated_images[0].image.image_bytes
    except Exception as e:
        print(f"Warning: Failed to generate feature image: {e}")
    return None

def create_product_collage(products):
    print("Generating fallback product collage...")
    image_urls = [p['image_url'] for p in products if p.get('image_url')]
    if not image_urls:
        print("No product images available for collage.")
        return None
        
    images = []
    target_height = 600
    for url in image_urls[:3]:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                aspect = img.width / img.height
                new_width = int(target_height * aspect)
                img = img.resize((new_width, target_height), Image.Resampling.LANCZOS)
                images.append(img)
        except Exception as e:
            print(f"Failed to fetch product image {url}: {e}")
            
    if not images:
        return None
        
    gap = 20
    border = 40
    bg_color = "#FDFBF7" # Cream color
    
    total_width = sum(img.width for img in images) + gap * (len(images) - 1) + border * 2
    total_height = target_height + border * 2
    
    collage = Image.new("RGBA", (total_width, total_height), bg_color)
    
    x_offset = border
    for img in images:
        collage.paste(img, (x_offset, border), img)
        x_offset += img.width + gap
        
    collage = collage.convert("RGB")
    byte_arr = io.BytesIO()
    collage.save(byte_arr, format='JPEG', quality=85)
    return byte_arr.getvalue()

def call_gemini_with_backoff(client, model_name, prompt, retries=3):
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            if '429' in str(e) or 'Quota' in str(e) or '403' in str(e) or '503' in str(e):
                wait_time = (2 ** attempt) * 5
                print(f"Rate limited by Gemini (Error: {e}). Waiting {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("Max retries exceeded for Gemini API")

def get_best_model(client):
    try:
        models_iterable = client.models.list()
        available_models = [m.name for m in models_iterable]
        print(f"Available models: {available_models}")
        
        # User requested priority: 3.1 or 2.5 flash
        priority = [
            "gemini-3.1-pro",
            "gemini-3.1-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro"
        ]
        
        # 1. Try to find a stable version first (no 'preview' or 'exp' in name)
        for p in priority:
            for m in available_models:
                if p in m and "preview" not in m and "exp" not in m:
                    print(f"Auto-selected requested model: {m}")
                    return m.replace('models/', '')
                    
        # 2. Try to find a preview version if stable isn't available
        for p in priority:
            for m in available_models:
                if p in m:
                    print(f"Auto-selected requested preview model: {m}")
                    return m.replace('models/', '')
                    
        # Fallback if no prioritized models found
        if available_models:
            return available_models[0].replace('models/', '')
    except Exception as e:
        print(f"Warning: Failed to dynamically list models: {e}")
        
    return 'gemini-2.5-flash'

def generate_blog_content(api_key, products, collections, existing_titles):
    client = genai.Client(api_key=api_key)
    model_name = get_best_model(client)
    print(f"Selected Gemini Text Model: {model_name}")
    
    exclusion_text = ""
    if existing_titles:
        exclusion_text = "DO NOT use any of these topics as we already covered them:\n" + "\n".join(f"- {t}" for t in existing_titles[:30]) + "\n"

    topic_prompt = (
        "Act as an expert SEO strategist for a women's fashion and lifestyle brand in the USA. "
        "Provide one specific, highly trending 'People Also Ask' style question that women shoppers are currently searching for. "
        f"It should be a helpful, practical question, NOT product-focused.\n{exclusion_text}"
        "Provide ONLY the question string, nothing else."
    )
    topic = call_gemini_with_backoff(client, model_name, topic_prompt).strip().strip('"')
    print(f"Trending Topic Selected: {topic}")
    
    # Extra safety check, if it somehow duplicated, we abort this run
    if topic in existing_titles:
        print("Generated a topic that already exists despite exclusions. Aborting this run to avoid duplicates.")
        sys.exit(0)
    
    context = ""
    if collections:
        context += "Here are some of our store collections you can subtly interlink in the text:\n"
        for c in collections:
            context += f"- {c['title']} (URL: {c['url']})\n"
            
    if products:
        context += "\nHere are 3 of our products to list casually at the very end of the article (under a 'Related Finds' or similar section). Do not explicitly recommend them, just mention them neutrally:\n"
        for p in products:
            context += f"- {p['title']} (URL: {p['url']})\n"
            
    article_prompt = f"""
Act as an expert fashion and lifestyle consultant. Write an SEO-optimized blog article answering this question: "{topic}".

STRICT GUIDELINES:
1. Target Audience: Women shoppers in the USA.
2. Tone: Active, conversational, first-person voice. Use real-world testing constraints or personal experiences.
3. Rhythm: Ensure "burstiness". Mix very short, punchy sentences with longer explanations. Do not use monotonous sentence structures.
4. Forbidden Words (AI Telltales): Do NOT use any of these phrases: {", ".join(AI_CLICHES)}.
5. Modern Layout & Formatting (CRITICAL):
   - Provide a high-quality main image meta tag at the top of the HTML (e.g., <meta name="max-image-preview" content="large" />).
   - The first line MUST be the <h1> title.
   - Use engaging <h2> subheadings.
   - Break up walls of text. Use <blockquote> for key takeaways or quotes.
   - Use bulleted lists (<ul>) with relevant emojis for easy scanning.
   - Bold important phrases. 
   - The article must genuinely help the reader and NOT sound like a sales pitch.
   - At the end, include a subtle section with the 3 provided products.
   - Interlink provided collections naturally within the text using HTML anchor tags.
6. Output Format: Return ONLY valid HTML. Do not wrap in ```html markdown blocks.

{context}
    """
    
    html_content = call_gemini_with_backoff(client, model_name, article_prompt)

    
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
        
    html_content = html_content.strip()
    
    title = topic
    if "<h1>" in html_content and "</h1>" in html_content:
        start = html_content.find("<h1>") + 4
        end = html_content.find("</h1>")
        title = html_content[start:end]
        html_content = html_content[:html_content.find("<h1>")] + html_content[end+5:]
        html_content = html_content.strip()

    return title, html_content

def get_recent_article_titles(session, store_url, blog_id):
    url = f"{store_url}/admin/api/2023-10/blogs/{blog_id}/articles.json?limit=50"
    resp = session.get(url)
    titles = []
    if resp.status_code == 200:
        articles = resp.json().get('articles', [])
        titles = [a.get('title') for a in articles]
    return titles

def main():
    # In GitHub Actions, we pass the decryption keys as env vars
    primary_key = os.environ.get("DECRYPTION_KEY_PRIMARY")
    fallback_key = os.environ.get("DECRYPTION_KEY_FALLBACK")
    
    if not primary_key or not fallback_key:
        print("Error: DECRYPTION_KEY_PRIMARY and DECRYPTION_KEY_FALLBACK environment variables must be set.")
        sys.exit(1)
        
    print("Decrypting credentials...")
    secrets = decrypt_secrets(primary_key.encode('utf-8'), fallback_key.encode('utf-8'))
    
    gemini_key = secrets.get("GEMINI_API_KEY")
    shopify_store = secrets.get("SHOPIFY_STORE_URL")
    shopify_token = secrets.get("SHOPIFY_ACCESS_TOKEN")
    
    if not all([gemini_key, shopify_store, shopify_token]):
        print("Error: Missing required secrets (GEMINI_API_KEY, SHOPIFY_STORE_URL, SHOPIFY_ACCESS_TOKEN).")
        sys.exit(1)
        
    shopify_store = shopify_store.rstrip('/')
        
    session = get_shopify_session(shopify_store, shopify_token)
    
    print("Fetching Shopify configuration...")
    blogs = get_shopify_blogs(session, shopify_store)
    if not blogs:
        print("Error: No blogs found on the Shopify store.")
        sys.exit(1)
    
    blog_id = blogs[0]['id']
    
    print("Checking for approved drafts to publish...")
    process_existing_drafts(session, shopify_store, blog_id)
    
    print("Fetching existing article titles...")
    existing_titles = get_recent_article_titles(session, shopify_store, blog_id)
    
    print("Fetching Shopify products and collections context...")
    products, collections = fetch_shopify_data(session, shopify_store)
    
    print("Generating blog content with Gemini...")
    title, html_content = generate_blog_content(gemini_key, products, collections, existing_titles)
    
    # Initialize the genai client for image generation
    client = genai.Client(api_key=gemini_key)
    image_bytes = generate_article_image(client, title)
    
    if not image_bytes:
        image_bytes = create_product_collage(products)
    
    print(f"Publishing new draft article: '{title}'...")
    author = "Editorial Team"
    article = publish_shopify_article(session, shopify_store, blog_id, title, html_content, author, image_bytes=image_bytes, draft=True)
    
    print(f"✅ Draft created successfully! Article ID: {article['id']}")

if __name__ == "__main__":
    main()
