import os
import sys
import requests
import json
import time

SCRIPT_DIR = r"c:\Users\USER\Downloads\Shopify_Claude\Shopify_Claude\repos\meeeshop-seo\meeeshop-seo"
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "scripts"))
sys.path.insert(0, SCRIPT_DIR)

from secrets_manager import inject_to_env, get_secret
inject_to_env()

try:
    import paa_pasf_seo_engine
except ImportError:
    paa_pasf_seo_engine = None


STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
GRAPHQL_ENDPOINT = f"https://{STORE}/admin/api/2024-10/graphql.json"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# Custom optimized SEO rules for all active collections
SEO_MAP = {
    # Brand Collections
    "ymi-jeans": {
        "title": "YMI Jeans Collection | WannaBettaButt & Hyperstretch Denim",
        "description": "Shop authentic YMI Jeans designed in Los Angeles. Discover YMI WannaBettaButt jeans, Hyperstretch pants, wide leg & flare denim with curve-defining fit. Free US shipping!"
    },
    "judy-blue-womens-jeans": {
        "title": "Judy Blue Jeans Collection | Tummy Control & Flare Denim",
        "description": "Shop authentic Judy Blue Jeans online. Discover tummy control jeans, high rise flare denim, stretchy wide leg & skinny fit jeans. Free US shipping!"
    },
    "pol-womens-clothing-collection": {
        "title": "POL Clothing Collection | Boho Tops & Vintage Style",
        "description": "Explore authentic POL Clothing online. Shop chic boho blouses, vintage lace tops, cozy cardigans & statement fashion essentials. Free US shipping!"
    },
    "risen-womens-jeans-collection": {
        "title": "Risen Jeans Collection | High Rise Bootcut & Baggy Denim",
        "description": "Shop trending Risen Jeans online. Discover tummy control bootcut jeans, slouchy wide leg denim & high rise skinny fits with stretch. Free US shipping!"
    },
    "kancan-usa-womens-jeans": {
        "title": "Kancan Jeans Collection | High Rise & 90s Boyfriend Denim",
        "description": "Shop authentic Kancan Jeans online. Discover signature high rise skinny jeans, 90s boyfriend denim & flattering flare styles. Free US shipping!"
    },
    "zenana-womens-clothing": {
        "title": "Zenana Women's Clothing | Soft Tops, Sweaters & Basics",
        "description": "Shop comfortable Zenana clothing online. Discover soft cotton tops, cozy knit cardigans, loungewear & everyday basics. Free US shipping!"
    },
    "umgee-usa-womens-clothing": {
        "title": "Umgee USA Clothing | Flowy Dresses & Floral Boho Tops",
        "description": "Shop trendy Umgee USA clothing online. Discover flowy floral dresses, smocked boho blouses & wide leg linen pants. Free US shipping!"
    },
    "flying-monkey-womens-jeans-collection": {
        "title": "Flying Monkey Jeans | Vintage Rigid & Stretch Denim",
        "description": "Shop authentic Flying Monkey jeans online. Discover vintage high rise denim, distressed flare jeans & classic stretch skinny fit. Free US shipping!"
    },
    "vervet-by-flying-monkey-womens-jeans": {
        "title": "VERVET by Flying Monkey | High Rise Flare & Wide Leg Jeans",
        "description": "Shop VERVET by Flying Monkey jeans online. Discover high rise flare denim, straight leg jeans & trendy wide leg fits. Free US shipping!"
    },
    "insane-gene-womens-denim": {
        "title": "Insane Gene Jeans | Trendy Wide Leg & Cargo Denim",
        "description": "Shop premium Insane Gene denim online. Discover wide leg cargo jeans, high rise flare fits & stylish distressed denim. Free US shipping!"
    },
    "vibrant-miu-womens-jeans": {
        "title": "Vibrant M.i.U Jeans | High Rise Skinny & Flare Denim",
        "description": "Shop authentic Vibrant M.i.U jeans online. Discover curve-flattering high rise skinny denim, flare pants & stretch jeans. Free US shipping!"
    },
    "hyfve-womens-clothing": {
        "title": "Hyfve Women's Clothing | Trendy Tops & Chic Rompers",
        "description": "Shop contemporary Hyfve clothing online. Discover chic button-up tops, stylish rompers & trendy modern fashion. Free US shipping!"
    },
    "bibi-womens-clothing": {
        "title": "Bibi Women's Clothing | Floral Prints & Satin Dresses",
        "description": "Shop stylish Bibi women's fashion online. Discover floral satin dresses, patterned blouses & trendy casual wear. Free US shipping!"
    },
    "white-birch-womens-clothing": {
        "title": "White Birch Clothing | Soft Knit Tops & Casual Sets",
        "description": "Shop authentic White Birch clothing online. Discover comfy knit tops, cozy cardigans & everyday lounge sets. Free US shipping!"
    },
    "heyson-clothing": {
        "title": "HEYSON Clothing | Chic Blouses & Everyday Fashion",
        "description": "Shop versatile HEYSON women's fashion online. Discover stylish blouses, elegant dresses & trendy daily apparel. Free US shipping!"
    },
    "yelete-womens-clothing": {
        "title": "Yelete Women's Clothing | Leggings, Activewear & Tops",
        "description": "Shop comfortable Yelete activewear online. Discover seamless leggings, soft active tops & everyday loungewear. Free US shipping!"
    },
    "culture-code-womens-clothing": {
        "title": "Culture Code Clothing | Trendy Graphic Tees & Basics",
        "description": "Shop chic Culture Code women's clothing online. Discover stylish graphic tees, comfortable casual tops & daily fashion. Free US shipping!"
    },
    "amoli": {
        "title": "Amoli Clothing Collection | Chic Tops & Trendy Fashion",
        "description": "Shop contemporary Amoli women's clothing online. Discover chic blouses, stylish dresses & versatile daily tops. Free US shipping!"
    },
    "la-miel-womens-clothing-collection": {
        "title": "LA MIEL Women's Clothing | Boho Tops & Cozy Sweaters",
        "description": "Shop LA MIEL women's apparel online. Discover trendy boho tops, cozy knit cardigans & stylish everyday outfits. Free US shipping!"
    },
    "hailey-co": {
        "title": "Hailey & Co | Elegant Dresses & Women's Tops",
        "description": "Shop Hailey & Co women's fashion online. Discover stylish dresses, elegant blouses & comfortable casual wear. Free US shipping!"
    },
    "oddi": {
        "title": "ODDI Clothing Collection | Floral Boho Tops & Cardigans",
        "description": "Shop authentic ODDI clothing online. Discover unique boho tops, thermal knit shirts & colorful print cardigans. Free US shipping!"
    },
    "kimberly-c": {
        "title": "Kimberly C Apparel | Soft Knit Tops & Everyday Basics",
        "description": "Shop comfortable Kimberly C women's apparel. Discover ultra-soft tops, casual sweaters & everyday fashion staples. Free US shipping!"
    },
    "orange-farm-womens-clothing": {
        "title": "Orange Farm Clothing | Casual Tops & Fashion Basics",
        "description": "Shop Orange Farm women's clothing online. Discover comfortable casual tops, blouses & cozy everyday wear. Free US shipping!"
    },
    "mustard-seed-womens-clothing": {
        "title": "Mustard Seed Clothing | Trendy Dresses & Tops",
        "description": "Shop Mustard Seed women's apparel online. Discover fashionable dresses, chic crop tops & modern wardrobe pieces. Free US shipping!"
    },
    "ninexis-womens-clothing-collection": {
        "title": "NINEXIS Clothing Collection | Soft Basics & Cardigans",
        "description": "Shop NINEXIS women's clothing online. Discover comfy knit cardigans, basic tops, loungewear & essential fashion. Free US shipping!"
    },
    "acting-pro-womens-clothing-collection-us-meeeshop": {
        "title": "Acting Pro Clothing | Everyday Tops & Casual Wear",
        "description": "Shop Acting Pro women's fashion online. Discover comfortable daily tops, relaxed blouses & versatile outfits. Free US shipping!"
    },
    "gilli-womens-clothing-collection": {
        "title": "Gilli Women's Clothing | Floral Dresses & Chic Jumpsuits",
        "description": "Shop stylish Gilli fashion online. Discover vibrant floral dresses, elegant maxi dresses & chic rompers. Free US shipping!"
    },
    "le-lis-womens-clothing": {
        "title": "LE LIS Women's Clothing | Modern Tops & Elegant Dresses",
        "description": "Shop refined LE LIS women's fashion online. Discover modern blouses, chic tailored tops & stylish dresses. Free US shipping!"
    },
    "lilou-womens-clothing-collection": {
        "title": "Lilou Women's Clothing | Feminine Dresses & Blouses",
        "description": "Shop romantic Lilou fashion online. Discover feminine floral dresses, delicate lace tops & stylish wardrobe favorites. Free US shipping!"
    },
    "one-and-only-collective-inc-womens-clothing": {
        "title": "One and Only Collective | Trendy Women's Apparel",
        "description": "Shop One and Only Collective apparel online. Discover statement tops, stylish denim jackets & trendy fashion pieces. Free US shipping!"
    },
    "heimish-usa-womens-clothing": {
        "title": "Heimish USA Clothing | Cozy Cardigans & Oversized Tops",
        "description": "Shop comfortable Heimish USA apparel online. Discover cozy waffle knit cardigans, oversized tops & soft lounge pants. Free US shipping!"
    },
    "petal-dew": {
        "title": "Petal Dew Clothing | Romantic Floral Dresses & Tops",
        "description": "Shop sweet Petal Dew women's apparel. Discover delicate floral print dresses, romantic blouses & summer fashion. Free US shipping!"
    },
    "emory-park-womens-clothing": {
        "title": "Emory Park Clothing | Chic Mini Dresses & Trendy Tops",
        "description": "Shop modern Emory Park women's apparel. Discover trendy mini dresses, stylish corsets & chic casual tops. Free US shipping!"
    },
    "justin-taylor-apparel-accessories": {
        "title": "Justin & Taylor | Accessories, Hats & Outerwear",
        "description": "Shop Justin & Taylor apparel & accessories online. Discover stylish winter hats, cozy scarves & fashion accessories. Free US shipping!"
    },
    "jade-by-jane-womens-clothing": {
        "title": "Jade By Jane | Contemporary Tops & Casual Wear",
        "description": "Shop Jade By Jane clothing online. Discover comfortable contemporary tops, casual jackets & versatile apparel. Free US shipping!"
    },
    "recycled-karma-womens-graphic-tees": {
        "title": "Recycled Karma | Vintage Rock & Band Graphic Tees",
        "description": "Shop authentic Recycled Karma graphic tees. Discover vintage rock band t-shirts, distressed retro tees & graphic tops. Free US shipping!"
    },
    "very-j-womens-clothing": {
        "title": "Very J Women's Clothing | Trendy Dresses & Tops",
        "description": "Shop Very J women's fashion online. Discover cute dresses, casual blouses, sweaters & contemporary wardrobe pieces. Free US shipping!"
    },
    "e-luna-womens-clothing": {
        "title": "e Luna Clothing | Contemporary Tops & Dresses",
        "description": "Shop e Luna women's apparel online. Discover modern stylish tops, comfortable dresses & versatile casual wear. Free US shipping!"
    },
    "artemis-vintage-womens-jeans": {
        "title": "Artemis Vintage Jeans | High Rise & Flare Denim",
        "description": "Shop Artemis Vintage jeans online. Discover vintage wash high rise jeans, flare denim & classic relaxed fit pants. Free US shipping!"
    },
    "celeste-clothing": {
        "title": "CELESTE Clothing | Chic Women's Fashion & Dresses",
        "description": "Shop CELESTE women's apparel online. Discover chic dresses, stylish blouses & elegant contemporary fashion. Free US shipping!"
    },

    # Category Collections
    "wide-leg-jeans": {
        "title": "Wide Leg Jeans for Women | Skater, Cargo & High Rise",
        "description": "Shop trending women's wide leg jeans online. Discover high rise skater cargo jeans, relaxed fit denim & baggy wide leg pants. Free US shipping!"
    },
    "flare-jeans": {
        "title": "Flare Jeans for Women | High Rise & Bootcut Denim",
        "description": "Shop stylish flare jeans for women. Discover high rise bell bottom denim, tummy control flare pants & classic stretch bootcut jeans. Free US shipping!"
    },
    "straight-leg-jeans": {
        "title": "Straight Leg Jeans for Women | High Rise & Ankle Denim",
        "description": "Shop classic straight leg jeans for women. Discover high rise straight leg denim, cropped ankle jeans & stretch fits. Free US shipping!"
    },
    "womens-jeans": {
        "title": "Women's Jeans Collection | High Rise, Wide Leg & Flare",
        "description": "Shop premium women's jeans online. Discover high rise skinny denim, wide leg cargo pants, tummy control flare jeans & bootcut styles. Free US shipping!"
    },
    "womens-jean-shorts": {
        "title": "Women's Jean Shorts | Cut-off, High Rise & Denim Jorts",
        "description": "Shop stylish women's denim shorts online. Discover high rise cut-offs, WannaBettaButt denim shorts & relaxed fit jorts. Free US shipping!"
    },
    "womens-denim-tops-jackets": {
        "title": "Women's Denim Jackets & Tops | Jean Vests & Shackets",
        "description": "Shop trendy denim jackets and tops for women. Discover boyfriend jean jackets, crop denim vests & button-up shackets. Free US shipping!"
    },
    "womens-tops": {
        "title": "Women's Tops & Blouses | Graphic Tees, Sweaters & Camis",
        "description": "Shop stylish women's tops online. Discover floral blouses, casual graphic tees, cozy knit sweaters & camisole tops. Free US shipping!"
    },
    "womens-knit-tops": {
        "title": "Women's Knit Tops | Soft Ribbed Tees & Long Sleeve Tops",
        "description": "Shop cozy women's knit tops online. Discover soft ribbed crewnecks, long sleeve knit tees & lightweight sweaters. Free US shipping!"
    },
    "womens-camis-tanks-tops": {
        "title": "Women's Camis & Tank Tops | Layering & Summer Tops",
        "description": "Shop chic women's camisoles and tank tops. Discover ribbed layering camis, floral tank tops & spaghetti strap summer tees. Free US shipping!"
    },
    "womens-t-shirts": {
        "title": "Women's T-Shirts & Tees | Graphic, Vintage & Crewneck",
        "description": "Shop comfortable women's t-shirts online. Discover classic crewneck tees, vintage graphic t-shirts & soft cotton tops. Free US shipping!"
    },
    "womens-shirts": {
        "title": "Women's Shirts & Blouses | Button-Down & Peplum Tops",
        "description": "Shop elegant women's shirts and blouses. Discover long sleeve button-downs, floral peplum tops & satin blouses. Free US shipping!"
    },
    "womens-blouses": {
        "title": "Women's Blouses | Floral, Chiffon & V-Neck Tops",
        "description": "Shop feminine women's blouses online. Discover floral print chiffon blouses, V-neck woven tops & ruffle sleeve tops. Free US shipping!"
    },
    "womens-dresses": {
        "title": "Women's Dresses Collection | Maxi, Midi & Mini Dresses",
        "description": "Shop gorgeous women's dresses online. Discover casual maxi dresses, elegant midi styles, floral mini dresses & party attire. Free US shipping!"
    },
    "womens-casual-dresses": {
        "title": "Women's Casual Dresses | Sundresses & T-Shirt Dresses",
        "description": "Shop effortless women's casual dresses. Discover relaxed sundresses, flowy tier dresses & soft t-shirt mini dresses. Free US shipping!"
    },
    "womens-maxi-dresses": {
        "title": "Women's Maxi Dresses | Flowy Floral & Tiered Long Dresses",
        "description": "Shop stunning women's maxi dresses online. Discover flowy floral maxi dresses, smocked tier dresses & halter long gowns. Free US shipping!"
    },
    "womens-cocktail-dresses": {
        "title": "Women's Cocktail Dresses | Party & Evening Midi Dresses",
        "description": "Shop chic cocktail dresses for women. Discover elegant party midi dresses, satin slip gowns & fitted evening dresses. Free US shipping!"
    },
    "womens-formal-evening-dresses": {
        "title": "Formal & Evening Dresses | Elegant Long Gowns & Party Wear",
        "description": "Shop glamorous formal and evening dresses. Discover floor-length gowns, velvet cocktail dresses & special occasion dresses. Free US shipping!"
    },
    "womens-sweaters": {
        "title": "Women's Sweaters & Cardigans | Knit Pullovers & Tops",
        "description": "Shop cozy women's sweaters online. Discover open-front cardigans, chunky knit pullovers & chic fall sweater tops. Free US shipping!"
    },
    "sweater-pullover": {
        "title": "Women's Sweater Pullovers | Chunky Knit & Crewneck Tops",
        "description": "Shop warm women's sweater pullovers. Discover chunky knit crewnecks, oversized pullovers & soft fall sweater tops. Free US shipping!"
    },
    "womens-cardigans": {
        "title": "Women's Cardigans | Open-Front, Button & Long Knit Sweaters",
        "description": "Shop versatile women's cardigans online. Discover open-front long cardigans, button-down knits & cozy duster sweaters. Free US shipping!"
    },
    "womens-sweatshirts": {
        "title": "Women's Sweatshirts | Casual Crewnecks & Fleece Pullovers",
        "description": "Shop comfortable women's sweatshirts online. Discover relaxed fleece crewnecks, oversized sweatshirts & casual pullovers. Free US shipping!"
    },
    "womens-sweatshirts-hoodies": {
        "title": "Women's Sweatshirts & Hoodies | Cozy Fleece & Pullovers",
        "description": "Shop soft women's sweatshirts and hoodies. Discover fleece zip-up hoodies, graphic pullovers & relaxed lounge tops. Free US shipping!"
    },
    "womens-outerwear": {
        "title": "Women's Jackets & Coats | Denim, Puffer & Pleather",
        "description": "Shop stylish women's coats and jackets. Discover boyfriend denim jackets, cozy puffer coats & chic pleather outerwear. Free US shipping!"
    },
    "womens-blazers-vests-jackets": {
        "title": "Women's Blazers, Vests & Jackets | Tailored & Casual Coats",
        "description": "Shop sharp women's blazers and vests. Discover open-front blazers, utility jackets & tailored suit vests. Free US shipping!"
    },
    "womens-skirts": {
        "title": "Women's Skirts | Mini, Midi & Denim Skirts",
        "description": "Shop stylish women's skirts online. Discover denim mini skirts, flowy tiered midi skirts & pleated cargo skorts. Free US shipping!"
    },
    "womens-pants-leggings": {
        "title": "Women's Pants & Leggings | Wide Leg, Cargo & Stretch Pants",
        "description": "Shop comfortable women's pants and leggings. Discover wide leg trousers, stretch cargo pants & high waist leggings. Free US shipping!"
    },
    "womens-shorts": {
        "title": "Women's Shorts | Denim Shorts, Cargo Skorts & Casual Shorts",
        "description": "Shop trendy women's shorts online. Discover high rise denim shorts, pleated cargo skorts & summer linen shorts. Free US shipping!"
    },
    "womens-active-tops": {
        "title": "Women's Active Tops | Workout Tanks & Sport Shirts",
        "description": "Shop performance active tops for women. Discover breathable workout tanks, sports crop tops & athletic tees. Free US shipping!"
    },
    "womens-active-bottoms": {
        "title": "Women's Active Bottoms | Leggings & Workout Shorts",
        "description": "Shop high-waist active leggings and shorts. Discover buttery-soft workout leggings, biker shorts & athletic pants. Free US shipping!"
    },
    "womens-rompers": {
        "title": "Women's Rompers & Jumpsuits | Casual & Party Rompers",
        "description": "Shop chic women's rompers and jumpsuits online. Discover strapless summer rompers, wide leg jumpsuits & tie-waist sets. Free US shipping!"
    },
    "womens-lounge-set": {
        "title": "Women's Lounge Sets | Matching Pajamas & Co-ord Outfits",
        "description": "Shop cozy women's lounge sets online. Discover soft matching pajama sets, rib-knit co-ords & casual sweat sets. Free US shipping!"
    },
    "womens-outfit-sets": {
        "title": "Women's Outfit Sets | Matching Two-Piece & Top Short Sets",
        "description": "Shop stylish matching outfit sets for women. Discover top and short co-ords, wide leg pant sets & two-piece outfits. Free US shipping!"
    },
    "womens-handbags-accessories": {
        "title": "Women's Handbags & Purses | Shoulder Bags & Backpacks",
        "description": "Shop trendy women's handbags and accessories. Discover oversize shoulder bags, signature backpacks & chic totes. Free US shipping!"
    },
    "womens-hats-scarves": {
        "title": "Women's Hats & Scarves | Winter Beanies & Accessories",
        "description": "Shop stylish women's hats and scarves. Discover knit winter beanies, trendy sun hats & cozy wrap scarves. Free US shipping!"
    },
    "womens-bodysuits": {
        "title": "Women's Bodysuits | Sleeveless, Ribbed & Contour Tops",
        "description": "Shop flattering women's bodysuits online. Discover ribbed sleeveless bodysuits, contour crewneck tops & lace bodysuits. Free US shipping!"
    },
    "womens-luxe-apparel": {
        "title": "Women's Luxe Apparel | Premium Fashion & Elegant Wear",
        "description": "Shop high-end luxury apparel for women. Discover premium silk blouses, elegant dresses & designer-quality outfits. Free US shipping!"
    },
    "womens-shoes": {
        "title": "Women's Shoes & Footwear | Sandals, Boots & Casual Shoes",
        "description": "Shop fashionable shoes for women. Discover trendy summer sandals, comfortable ankle boots & everyday footwear. Free US shipping!"
    },
    "womens-sleepwear": {
        "title": "Women's Sleepwear & Pajamas | Soft Sets & Nightgowns",
        "description": "Shop comfortable women's sleepwear online. Discover soft pajama sets, satin nightgowns & cozy loungewear. Free US shipping!"
    },

    # Curated / Promotional Collections
    "womens-curvy-plus-size-clothing": {
        "title": "Women's Plus Size & Curvy Clothing | Jeans, Tops & Dresses",
        "description": "Shop flattering plus size and curvy clothing for women. Discover tummy control jeans, flowy tops & stylish plus dresses. Free US shipping!"
    },
    "sale-plus-size-apparel": {
        "title": "Sale Plus Size Apparel | Discounted Tops, Jeans & Dresses",
        "description": "Shop deals on plus size women's clothing. Save on curvy fit jeans, flowy tops, dresses & cozy cardigans. Free US shipping!"
    },
    "made-in-usa": {
        "title": "Made in USA Women's Clothing | American Made Fashion",
        "description": "Shop authentic Made in USA women's clothing. Discover high quality American-made tops, dresses & boutique fashion. Free US shipping!"
    },
    "usa-sale": {
        "title": "USA Fashion Sale | Discounted Women's Tops & Jeans",
        "description": "Shop the USA women's fashion sale. Save on trending tops, designer denim, dresses & accessories. Free US shipping!"
    },
    "selected-usa-styles": {
        "title": "Selected USA Styles | Featured Women's Boutique Clothing",
        "description": "Discover selected USA boutique clothing for women. Shop top-trending tops, high rise denim & stylish dresses. Free US shipping!"
    },
    "under-50": {
        "title": "Women's Fashion Under $50 | Affordable Tops & Jeans",
        "description": "Shop budget-friendly women's fashion under $50. Discover stylish tops, trendy jeans, dresses & accessories. Free US shipping!"
    },
    "under-40": {
        "title": "Women's Clothing Under $40 | Affordable Trendy Outfits",
        "description": "Shop affordable women's fashion under $40. Discover chic blouses, graphic tees, shorts & everyday basics. Free US shipping!"
    },
    "womens-new-collection": {
        "title": "New Arrivals Women's Fashion | Latest Clothing & Denim",
        "description": "Shop the latest new arrivals in women's fashion. Discover newly added tops, trending jeans, dresses & accessories. Free US shipping!"
    },
    "womens-best-selling-collection": {
        "title": "Best Selling Women's Fashion | Top Rated Jeans & Tops",
        "description": "Shop best selling women's clothing online. Discover customer-favorite jeans, top-rated blouses & popular dresses. Free US shipping!"
    },
    "womens-graphic-tees": {
        "title": "Women's Graphic Tees | Vintage Band & Retro T-Shirts",
        "description": "Shop cool women's graphic tees online. Discover vintage band t-shirts, retro slogan tops & relaxed fit graphic tees. Free US shipping!"
    },
    "womens-loungewear": {
        "title": "Women's Loungewear & Basics | Soft Sets & Casual Pants",
        "description": "Shop cozy women's loungewear online. Discover soft lounge pants, casual knit sets & comfortable daily wear. Free US shipping!"
    },
    "womens-tunics": {
        "title": "Women's Tunics & Flowy Tops | Long Sleeve & Boho Tops",
        "description": "Shop stylish women's tunics online. Discover long flowy tunic tops, boho tie-front shirts & versatile tunic dresses. Free US shipping!"
    },
    "womens-coats-jackets": {
        "title": "Women's Coats & Jackets | Denim, Puffer & Pleather",
        "description": "Shop stylish women's coats and jackets. Discover boyfriend denim jackets, cozy puffer coats & chic pleather outerwear. Free US shipping!"
    },
    "womens-new-denim": {
        "title": "New Arrivals Denim & Jeans | Latest High Rise & Flare Fits",
        "description": "Shop new arrival women's jeans and denim. Discover fresh high rise wide leg jeans, cargo shorts & flare denim. Free US shipping!"
    },
    "trending-product-pins": {
        "title": "Trending Women's Fashion Pins | Viral Outfit Ideas",
        "description": "Shop trending Pinterest fashion pins & viral women's outfits. Discover popular tops, wide leg jeans & dresses. Free US shipping!"
    },
    "black-friday-chic-trendy-womens-fashion-deals-discounts": {
        "title": "Black Friday Fashion Deals | Women's Clothing Discounts",
        "description": "Shop Black Friday deals on women's clothing. Save big on top-selling jeans, trendy tops, dresses & outerwear. Free US shipping!"
    },
    "25-percent-off": {
        "title": "25% Off Women's Fashion Sale | Discounted Clothing",
        "description": "Shop our 25% off fashion sale. Save on trending women's jeans, stylish tops, dresses & fashion accessories. Free US shipping!"
    },
    "fall-clothing-for-women": {
        "title": "Fall Clothing for Women | Cozy Sweaters, Jackets & Jeans",
        "description": "Shop fall fashion essentials for women. Discover cozy knit sweaters, denim jackets, cargo pants & autumn dresses. Free US shipping!"
    },
    "zenana-sweaters": {
        "title": "Zenana Sweaters & Knit Tops | Cozy Cardigans & Pullovers",
        "description": "Shop comfortable Zenana sweaters online. Discover soft knit pullovers, open-front cardigans & cozy fall tops. Free US shipping!"
    },
    "zenana-dresses": {
        "title": "Zenana Dresses | Casual Sundresses & T-Shirt Dresses",
        "description": "Shop comfortable Zenana dresses online. Discover relaxed t-shirt dresses, casual midi styles & easy everyday wear. Free US shipping!"
    },
    "zenana-tops": {
        "title": "Zenana Tops & Tees | Soft Cotton Tops & Layering Camis",
        "description": "Shop Zenana women's tops online. Discover soft cotton t-shirts, ribbed tank tops & essential layering camis. Free US shipping!"
    },
    "zenana-sweatshirts": {
        "title": "Zenana Sweatshirts & Hoodies | Soft Fleece Pullovers",
        "description": "Shop cozy Zenana sweatshirts online. Discover soft fleece crewnecks, relaxed hoodies & casual lounge pullovers. Free US shipping!"
    },
    "zenana-shorts": {
        "title": "Zenana Shorts | Casual Biker Shorts & Lounge Shorts",
        "description": "Shop comfortable Zenana shorts online. Discover stretch biker shorts, soft cotton lounge shorts & casual summer bottoms. Free US shipping!"
    },
    "christmas-gift-collection": {
        "title": "Christmas Gift Guide | Holiday Outfits & Fashion Gifts",
        "description": "Shop top Christmas gifts for women. Discover cozy sweaters, stylish accessories, trendy outerwear & festive outfits. Free US shipping!"
    },
    "holiday-outfit-ideas": {
        "title": "Holiday Outfit Ideas | Festive Dresses, Tops & Sweaters",
        "description": "Shop stylish holiday outfit ideas for women. Discover glamorous festive dresses, velvet tops & cozy winter sweaters. Free US shipping!"
    }
}

def update_all_collections(target_handle: str = None, dry_run: bool = False, force: bool = False):
    # Query all active collections from Shopify
    query = """
    query {
      collections(first: 250) {
        edges {
          node {
            id
            title
            handle
            productsCount {
              count
            }
          }
        }
      }
    }
    """
    
    resp = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": query})
    data = resp.json()
    edges = data.get("data", {}).get("collections", {}).get("edges", [])
    
    updated_count = 0
    skipped_count = 0
    
    print(f"Loaded {len(edges)} total collections from Shopify. Beginning SEO updates...\n")
    
    seo_mutation = """
    mutation collectionUpdate($input: CollectionInput!) {
      collectionUpdate(input: $input) {
        collection {
          id
          title
          handle
          seo {
            title
            description
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    for edge in edges:
        c = edge["node"]
        handle = c["handle"]
        gid = c["id"]
        title = c["title"]
        count = c["productsCount"]["count"] if c.get("productsCount") else 0
        
        # Filter by target handle if specified
        if target_handle and handle.lower() != target_handle.lower():
            continue

        # Skip hidden empty collections or special system collection
        if count == 0 and handle not in SEO_MAP:
            continue
        if handle == "all-products_do_not_delete":
            continue
            
        # Check 60-day stability lock to prevent content churn (unless --force)
        if not force and paa_pasf_seo_engine and paa_pasf_seo_engine.is_recently_updated(f"collection:{handle}"):
            print(f"[SKIP LOCK] Collection '{handle}' updated within last 60 days.")
            skipped_count += 1
            continue

        seo_data = SEO_MAP.get(handle)
        
        if paa_pasf_seo_engine:
            try:
                dyn_title, dyn_desc = paa_pasf_seo_engine.generate_optimized_collection_seo(title)
                seo_title = dyn_title if dyn_title else (seo_data["title"] if seo_data else f"{title} | MeeeShop")
                seo_desc = dyn_desc if dyn_desc else (seo_data["description"] if seo_data else f"Shop {title} at MeeeShop.")
            except Exception as e:
                print(f"[PASF Engine Warning] {handle}: {e}")
                seo_title = seo_data["title"] if seo_data else f"{title} | MeeeShop"
                seo_desc = seo_data["description"] if seo_data else f"Shop {title} at MeeeShop."
        elif not seo_data:
            # Fallback generator for any remaining collection
            clean_title = title.replace("Collection", "").replace("Clothing", "").strip()
            seo_title = f"{title} | Women's Fashion & Apparel"
            if len(seo_title) > 60:
                seo_title = f"{clean_title} | Women's Fashion"
            seo_desc = f"Shop {title} online at Meeeshop. Discover trending women's fashion, stylish outfits & premium quality apparel. Free US shipping!"
        else:
            seo_title = seo_data["title"]
            seo_desc = seo_data["description"]
            
        print(f"[TARGET COLLECTION]: {title} ({handle})")
        print(f"   SEO Title: {seo_title}")
        print(f"   SEO Desc : {seo_desc}")

        if dry_run:
            print(f"   [DRY-RUN / DIAGNOSE] Skipping Shopify API mutation.")
            updated_count += 1
            print("-" * 60)
            continue

        variables = {
            "input": {
                "id": gid,
                "seo": {
                    "title": seo_title,
                    "description": seo_desc
                }
            }
        }
        
        if paa_pasf_seo_engine:
            paa_pasf_seo_engine.log_entity_update(f"collection:{handle}")
        
        res = requests.post(GRAPHQL_ENDPOINT, headers=HEADERS, json={"query": seo_mutation, "variables": variables})
        res_json = res.json()
        
        errors = res_json.get("data", {}).get("collectionUpdate", {}).get("userErrors", [])
        if errors:
            print(f"[ERROR] updating {handle}: {errors}")
        else:
            updated_count += 1
            print(f"   [LIVE UPDATED SUCCESS]")
            print("-" * 60)
            
        time.sleep(0.15)
        
    print(f"\n[DONE] Finished! Total updated/processed: {updated_count}, Skipped (Locked): {skipped_count}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bulk Update Shopify Collection SEO Titles & Descriptions with PAA/PASF Engine")
    parser.add_argument("--handle", type=str, default=None, help="Target specific collection handle (e.g. judy-blue-womens-jeans)")
    parser.add_argument("--diagnose", action="store_true", help="Preview mode without calling live Shopify mutation")
    parser.add_argument("--force", action="store_true", help="Ignore 60-day stability lock and force update")
    args = parser.parse_args()

    update_all_collections(target_handle=args.handle, dry_run=args.diagnose, force=args.force)
