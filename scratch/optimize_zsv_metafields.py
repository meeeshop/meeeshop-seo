import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()
from shopify_graphql import fetch_collections_graphql, run_graphql

# Load matched sitemap collections
with open("scratch/matched_collections.json", "r", encoding="utf-8") as f:
    matched = json.load(f)
sitemap_handles = {item[1] for item in matched}

# Optimized metadata mapping:
# handle -> (SEO Title, SEO Description, Normal Title, Normal Description HTML)
OPTIMIZED_SEO = {
    "emory-park-womens-clothing": (
        "Emory Park Clothing for Women | Boutique Styles at MeeeShop",
        "Shop the latest Emory Park women's clothing collection. Enjoy chic designs, comfy fits, and trendy boutique pieces. Free US shipping & 7-day returns.",
        "Emory Park Women's Clothing",
        "<p>Shop the latest Emory Park women's clothing collection at MeeeShop. Discover chic, trendy boutique pieces designed for the modern woman. All orders include free US shipping and a hassle-free 7-day return policy.</p>"
    ),
    "pol-womens-clothing-collection": (
        "POL Clothing Collection for Women | Bohemian Boutique Styles",
        "Discover bohemian-inspired POL clothing at MeeeShop. Featuring lace, knits, thermals, and vintage-wash styles. Free US shipping on all orders!",
        "POL Clothing Collection",
        "<p>Explore bohemian-inspired POL clothing for women at MeeeShop. Featuring high-quality lace, cozy knits, thermals, and vintage-wash styles. All orders include free US shipping and a hassle-free 7-day return policy.</p>"
    ),
    "zenana-womens-clothing": (
        "Zenana Women's Clothing & Basics | High-Quality Essentials",
        "Shop comfortable Zenana basics, activewear, tees, and lounge sets at MeeeShop. Made for everyday style with soft fabrics. Free US shipping & returns.",
        "Zenana Women's Clothing",
        "<p>Shop premium Zenana basics, activewear, tees, and lounge sets at MeeeShop. Crafted for comfort and effortless daily style. Enjoy free US shipping and a hassle-free 7-day return policy.</p>"
    ),
    "judy-blue-womens-jeans": (
        "Judy Blue Jeans for Women | Ultra Stretchy & Comfort Fit",
        "Shop the ultimate collection of Judy Blue jeans at MeeeShop. Famous for premium stretch, tummy control, and flattering fits. Free US shipping!",
        "Judy Blue Jeans",
        "<p>Experience the ultimate comfort and stretch with Judy Blue jeans at MeeeShop. Famous for tummy control, flattering fits, and premium denim. All orders include free US shipping and a 7-day return policy.</p>"
    ),
    "risen-womens-jeans-collection": (
        "Risen Jeans Collection for Women | Trendy Stretch Denim",
        "Browse premium Risen Jeans at MeeeShop. Discover chic distressed styles, straight leg, and flare jeans with comfortable stretch. Fast free US shipping.",
        "Risen Jeans Collection",
        "<p>Browse premium Risen Jeans for women at MeeeShop. Discover distressed styles, straight leg, and classic flare jeans with comfortable stretch. Enjoy fast free US shipping and our 7-day return policy.</p>"
    ),
    "hyfve-womens-clothing": (
        "Hyfve Clothing for Women | Modern Boutique Styles",
        "Shop trendy Hyfve women's apparel at MeeeShop. Discover chic dresses, tops, and outer layer styles for the modern woman. Free US shipping & returns.",
        "Hyfve Women's Clothing",
        "<p>Shop the modern and trendy Hyfve women's apparel collection at MeeeShop. Explore chic dresses, fashionable tops, and outer layers. All orders feature free US shipping and a 7-day return policy.</p>"
    ),
    "umgee-usa-womens-clothing": (
        "Umgee USA Clothing | Bohemian & Casual Women's Styles",
        "Explore casual, bohemian-inspired Umgee USA women's clothing at MeeeShop. Perfect flowy cuts, cardigans, and dresses. Enjoy free US shipping!",
        "Umgee USA Clothing",
        "<p>Explore flowy, bohemian-inspired Umgee USA women's clothing at MeeeShop. Featuring gorgeous cardigans, comfortable dresses, and casual fits. Free US shipping and 7-day returns included.</p>"
    ),
    "bibi-womens-clothing": (
        "Bibi Clothing for Women | Fun & Expressive Boutique Fashion",
        "Shop expressive and fun Bibi women's clothing at MeeeShop. Featuring unique prints, cozy knits, and comfortable everyday wear. Free shipping in the US!",
        "Bibi Clothing",
        "<p>Shop bold, expressive, and fun Bibi women's clothing at MeeeShop. Discover unique prints, cozy knits, and comfortable everyday boutique fashion. Free US shipping and 7-day returns on all items.</p>"
    ),
    "artemis-vintage-womens-jeans": (
        "Artemis Vintage Jeans for Women | Classic Denim Styles",
        "Shop premium Artemis Vintage jeans at MeeeShop. Durable denim, classic washes, and timeless fits designed for every day. Free shipping in the US.",
        "Artemis Vintage Jeans",
        "<p>Explore premium Artemis Vintage jeans at MeeeShop. Featuring durable classic denim, timeless washes, and comfortable fits designed for daily wear. Includes free US shipping and 7-day returns.</p>"
    ),
    "fall-clothing-for-women": (
        "Fall Clothing for Women | Cozy Autumn Boutique Styles",
        "Transition your wardrobe with cozy fall clothing for women at MeeeShop. Explore sweaters, cardigans, long sleeve tops, and denim. Free US shipping.",
        "Fall Clothing for Women",
        "<p>Transition your wardrobe with cozy fall clothing for women at MeeeShop. Explore trendy sweaters, cardigans, long sleeve tops, and stretch denim. Enjoy free US shipping and a 7-day return policy.</p>"
    ),
    "made-in-usa": (
        "Made in USA Women's Clothing | Premium American Fashion",
        "Shop high-quality, ethically made in USA clothing at MeeeShop. Support local manufacturing while enjoying premium fashion. Free US shipping.",
        "Made in USA Clothing",
        "<p>Shop high-quality, ethically made in USA women's clothing at MeeeShop. Support local craftsmanship while enjoying premium fashion essentials. Free US shipping and 7-day returns on all orders.</p>"
    ),
    "womens-curvy-plus-size-clothing": (
        "Curvy & Plus Size Clothing for Women | Boutique Fits",
        "Find flattering, comfortable curvy and plus size women's clothing at MeeeShop. Shop stretch denim, jumpsuits, and casual tops. Free US shipping!",
        "Curvy & Plus Size Clothing",
        "<p>Find flattering, comfortable curvy and plus size women's clothing at MeeeShop. Explore stretch denim, casual tops, and chic jumpsuits. Free US shipping and our hassle-free 7-day return policy.</p>"
    ),
    "womens-handbags-accessories": (
        "Women's Handbags & Accessories | Chic Boutique Style",
        "Complete your look with chic women's handbags and accessories from MeeeShop. Discover trendy bags, purses, and style additions. Free shipping!",
        "Women's Handbags & Accessories",
        "<p>Complete your outfit with chic women's handbags and boutique accessories from MeeeShop. Discover trendy bags, purses, and statement additions. Enjoy free US shipping and a 7-day return policy.</p>"
    ),
    "womens-rompers-jumpsuit-sets": (
        "Women's Rompers, Jumpsuits & Sets | Casual Styling",
        "Discover easy, comfortable women's rompers, jumpsuits, and matching sets at MeeeShop. Effortless styling for active and lounge days. Free shipping.",
        "Women's Rompers & Jumpsuits",
        "<p>Discover comfortable, easy-to-wear women's rompers, jumpsuits, and matching sets at MeeeShop. Perfect for active days, lounging, or styling up. Free US shipping and 7-day returns included.</p>"
    ),
    "womens-sweaters": (
        "Women's Sweaters & Knits | Cozy Boutique Styles",
        "Stay warm with cozy women's sweaters and knits at MeeeShop. Perfect for layering in classic colors and trendy designs. Free US shipping.",
        "Women's Sweaters",
        "<p>Stay warm in style with cozy women's sweaters and knits at MeeeShop. Ideal for layering in classic colors and trendy knit designs. Enjoy free US shipping and a 7-day return policy.</p>"
    ),
    "womens-cardigans": (
        "Women's Cardigans & Dusters | Light Layering Pieces",
        "Browse comfortable women's cardigans and dusters at MeeeShop. Find long, cropped, and knit layering options. Free shipping in the US.",
        "Women's Cardigans",
        "<p>Browse comfortable women's cardigans and long dusters at MeeeShop. Find lightweight, cropped, and knit layering options. All orders feature free US shipping and 7-day returns.</p>"
    ),
    "womens-maxi-dresses": (
        "Women's Maxi Dresses | Flowy & Elegant Styles",
        "Shop beautiful women's maxi dresses at MeeeShop. Flowy cuts, casual floral patterns, and elegant styles for any occasion. Free shipping.",
        "Women's Maxi Dresses",
        "<p>Shop beautiful, flowy maxi dresses for women at MeeeShop. Discover elegant cuts, floral patterns, and casual styles perfect for any occasion. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-casual-dresses": (
        "Women's Casual Dresses | Easy Everyday Boutique Style",
        "Find your new favorite everyday look with casual dresses for women at MeeeShop. Easy wear, soft fabrics, and stylish cuts. Free US shipping.",
        "Women's Casual Dresses",
        "<p>Find your new favorite everyday look with casual dresses for women at MeeeShop. Featuring soft fabrics, easy wear, and stylish fits. Free US shipping and a 7-day return policy.</p>"
    ),
    "womens-cocktail-dresses": (
        "Women's Cocktail & Party Dresses | Semi-Formal Styles",
        "Make a statement with women's cocktail and party dresses at MeeeShop. Flattering semi-formal designs for events and evenings. Free shipping.",
        "Women's Cocktail Dresses",
        "<p>Make a statement with women's cocktail and party dresses at MeeeShop. Discover flattering semi-formal designs for events, parties, and evenings out. Includes free US shipping and 7-day returns.</p>"
    ),
    "womens-dresses": (
        "Women's Dresses & Jumpsuits | Chic Boutique Designs",
        "Explore the complete range of women's dresses at MeeeShop. From casual shifts to elegant maxi dresses and trendy midis. Free US shipping.",
        "Women's Dresses",
        "<p>Explore the complete collection of women's dresses at MeeeShop. From casual shifts and comfortable midis to elegant flowy maxi dresses. Enjoy free US shipping and a 7-day return policy.</p>"
    ),
    "womens-shirts": (
        "Women's Shirts & Blouses | Office to Casual Styling",
        "Shop elegant women's shirts, button-downs, and blouses at MeeeShop. Perfect for work, daily layering, or styling up. Free shipping.",
        "Women's Shirts & Blouses",
        "<p>Shop elegant women's shirts, button-downs, and blouses at MeeeShop. Perfect for professional office looks or casual layering. Free US shipping and 7-day returns included.</p>"
    ),
    "womens-camis-tanks-tops": (
        "Women's Camis, Tanks & Tops | Premium Basics",
        "Explore layering essentials with women's camis, tanks, and basic tops at MeeeShop. Soft fabrics, great stretch, and classic cuts. Free shipping.",
        "Women's Camis & Tanks",
        "<p>Explore essential layering basics with women's camis, tanks, and tops at MeeeShop. Made with soft fabrics, great stretch, and classic cuts. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-knit-tops": (
        "Women's Knit Tops & Sweaters | Soft Texture Styles",
        "Find textured comfort with women's knit tops and lightweight sweaters at MeeeShop. Flattering styles for transitional seasons. Free US shipping.",
        "Women's Knit Tops",
        "<p>Find textured comfort with women's knit tops and lightweight sweaters at MeeeShop. Flattering styles designed for easy styling and transitional seasons. Free US shipping and 7-day returns.</p>"
    ),
    "womens-t-shirts": (
        "Women's T-Shirts & Graphic Tees | Comfy Boutique Basics",
        "Shop casual everyday women's t-shirts and tees at MeeeShop. Relaxed fits, soft premium cottons, and stylish basics. Free shipping in the US.",
        "Women's T-Shirts",
        "<p>Shop comfortable everyday women's t-shirts and graphic tees at MeeeShop. Relaxed fits, soft premium cottons, and stylish basics. Enjoy free US shipping and a 7-day return policy.</p>"
    ),
    "womens-tops": (
        "Women's Tops & Tees | Trendy Boutique Styles",
        "Discover the latest collection of women's tops at MeeeShop. From casual graphic tees to elegant blouses and tanks. Free shipping in the US.",
        "Women's Tops",
        "<p>Discover the latest collection of women's tops at MeeeShop. From casual tees and basics to elegant blouses and fashion tops. All orders include free US shipping and 7-day returns.</p>"
    ),
    "womens-outerwear": (
        "Women's Outerwear, Jackets & Coats | Chic Layers",
        "Stay warm in style with women's outerwear, jackets, and coats at MeeeShop. Featuring denim jackets, trench coats, and cozy shackets. Free shipping.",
        "Women's Outerwear",
        "<p>Stay warm in style with women's outerwear, jackets, and coats at MeeeShop. Explore classic denim jackets, trench coats, and cozy shackets. Free US shipping and 7-day returns included.</p>"
    ),
    "womens-bottoms": (
        "Women's Bottoms, Pants & Skirts | Flattering Cuts",
        "Shop the complete range of women's bottoms at MeeeShop. Discover jeans, casual pants, shorts, and skirts designed for fit. Free US shipping.",
        "Women's Bottoms",
        "<p>Shop the complete range of women's bottoms at MeeeShop. Discover comfortable jeans, pants, shorts, and skirts designed for style and fit. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-pants-leggings": (
        "Women's Pants & Leggings | Comfortable Daily Wear",
        "Find everyday comfort with women's pants, joggers, and leggings at MeeeShop. Flattering fits, stretchy materials, and classic colors. Free shipping.",
        "Women's Pants & Leggings",
        "<p>Find everyday comfort with women's pants, joggers, and leggings at MeeeShop. Flattering fits, stretchy materials, and classic colors. Includes free US shipping and 7-day returns.</p>"
    ),
    "womens-shorts": (
        "Women's Shorts & Denim Cutoffs | Spring & Summer Wear",
        "Prepare for warm weather with women's shorts and denim cutoffs at MeeeShop. Comfortable mid-rise and high-rise fits. Free US shipping.",
        "Women's Shorts",
        "<p>Prepare for warm weather with women's shorts and denim cutoffs at MeeeShop. Featuring comfortable mid-rise and high-rise fits. Free US shipping and 7-day returns on all orders.</p>"
    ),
    "womens-skirts": (
        "Women's Skirts & Skorts | Flowy & Casual Designs",
        "Discover stylish women's skirts and casual skorts at MeeeShop. From flowy floral maxis to classic denim skirts. Free shipping in the US.",
        "Women's Skirts",
        "<p>Discover stylish women's skirts and casual skorts at MeeeShop. From flowy floral maxis to classic denim skirts. All orders feature free US shipping and 7-day returns.</p>"
    ),
    "womens-jeans": (
        "Women's Jeans & Premium Denim | Bootcut, Straight & Flare",
        "Find your perfect pair with women's jeans and premium denim at MeeeShop. Stretchy fits, flattering washes, and trendy styles. Free shipping.",
        "Women's Jeans",
        "<p>Find your perfect pair with women's jeans and premium denim at MeeeShop. Featuring bootcut, straight, and flare styles designed for ultimate fit. Free US shipping and 7-day returns.</p>"
    ),
    "womens-denim-tops-jackets": (
        "Women's Denim Tops, Jackets & Vests | Classic Layering",
        "Shop classic women's denim tops, jean jackets, and denim vests at MeeeShop. Timeless casual layers with modern comfort. Free shipping.",
        "Women's Denim Tops & Jackets",
        "<p>Shop classic women's denim tops, jean jackets, and denim vests at MeeeShop. Timeless casual layers with modern comfort. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-sweatshirts": (
        "Women's Sweatshirts & Pullovers | Cozy Loungewear",
        "Stay cozy with casual sweatshirts and pullovers for women at MeeeShop. Soft fleece, relaxed fits, and trendy graphic styles. Free US shipping.",
        "Women's Sweatshirts",
        "<p>Stay cozy with casual sweatshirts and pullovers for women at MeeeShop. Soft fleece, relaxed fits, and trendy graphic styles. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-sweatshirts-hoodies": (
        "Women's Sweatshirts & Hoodies | Relaxed Casual Styles",
        "Discover relaxed women's sweatshirts, hoodies, and pullovers at MeeeShop. Cozy comfort for loungewear or street styling. Free shipping.",
        "Women's Sweatshirts & Hoodies",
        "<p>Discover relaxed women's sweatshirts, hoodies, and pullovers at MeeeShop. Cozy comfort perfect for loungewear or street styling. Free US shipping and 7-day returns.</p>"
    ),
    "womens-hoodies": (
        "Women's Hoodies & Zip-Ups | Sporty Boutique Comfort",
        "Shop casual women's hoodies and active zip-up jackets at MeeeShop. Relaxed fits and cozy fabrics for perfect everyday wear. Free shipping.",
        "Women's Hoodies",
        "<p>Shop casual women's hoodies and active zip-up jackets at MeeeShop. Relaxed fits and cozy fabrics for perfect everyday wear. Enjoy free US shipping and a 7-day return policy.</p>"
    )
}

def set_seo_metafields(collection_id, title_tag, desc_tag):
    owner_id = f"gid://shopify/Collection/{collection_id}"
    query = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields {
          id
          namespace
          key
          value
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    metafields = []
    if title_tag:
        metafields.append({
            "ownerId": owner_id,
            "namespace": "global",
            "key": "title_tag",
            "type": "single_line_text_field",
            "value": title_tag
        })
    if desc_tag:
        metafields.append({
            "ownerId": owner_id,
            "namespace": "global",
            "key": "description_tag",
            "type": "multi_line_text_field",
            "value": desc_tag
        })
        
    variables = {"metafields": metafields}
    res = run_graphql(query, variables)
    errors = res.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
    if errors:
        print(f"Error setting SEO metafields for {owner_id}: {errors}")
        return False
    return True

def update_collection_normal_fields(collection_id, normal_title, normal_desc):
    owner_id = f"gid://shopify/Collection/{collection_id}"
    query = """
    mutation collectionUpdate($input: CollectionInput!) {
      collectionUpdate(input: $input) {
        collection {
          id
          title
          descriptionHtml
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {
        "input": {
            "id": owner_id,
            "title": normal_title,
            "descriptionHtml": normal_desc
        }
    }
    res = run_graphql(query, variables)
    errors = res.get("data", {}).get("collectionUpdate", {}).get("userErrors", [])
    if errors:
        print(f"Error updating collection fields for {owner_id}: {errors}")
        return False
    return True

print("Fetching current collections from Shopify...")
all_collections = fetch_collections_graphql()

updated_seo_count = 0
updated_normal_count = 0
for col in all_collections:
    handle = col["handle"]
    if handle in OPTIMIZED_SEO:
        new_seo_title, new_seo_desc, new_normal_title, new_normal_desc = OPTIMIZED_SEO[handle]
        
        # Check if SEO already optimized
        current_title = None
        current_desc = None
        for m in col["metafields"]:
            if m["namespace"] == "global" and m["key"] == "title_tag":
                current_title = m["value"]
            elif m["namespace"] == "global" and m["key"] == "description_tag":
                current_desc = m["value"]
                
        seo_needs_update = (current_title != new_seo_title or current_desc != new_seo_desc)
        normal_needs_update = (col["title"] != new_normal_title or col["body_html"] != new_normal_desc)
        
        if not seo_needs_update and not normal_needs_update:
            print(f"Collection {col['title']} is already fully optimized.")
            continue
            
        print(f"Optimizing: {col['title']}...")
        if seo_needs_update:
            print(f"  Updating SEO Title & Description...")
            success = set_seo_metafields(col["id"], new_seo_title, new_seo_desc)
            if success:
                updated_seo_count += 1
                print(f"    [OK] Updated SEO Metafields")
        
        if normal_needs_update:
            print(f"  Updating normal Title & Description HTML...")
            success = update_collection_normal_fields(col["id"], new_normal_title, new_normal_desc)
            if success:
                updated_normal_count += 1
                print(f"    [OK] Updated Normal Fields")

print(f"\nOptimization complete!")
print(f"Total collections updated (SEO): {updated_seo_count}")
print(f"Total collections updated (Normal): {updated_normal_count}")
