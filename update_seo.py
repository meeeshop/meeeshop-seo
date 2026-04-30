#!/usr/bin/env python3
"""
MeeeShop SEO Updater
- Backs up current collection SEO to seo_backup_<timestamp>.json
- Updates meta titles + descriptions on all 47 collections
- Goal: organic traffic from women shoppers in USA
"""

import json, re, time, sys
from datetime import datetime

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

SHOP        = "us-meeeshop.myshopify.com"
TOKEN       = "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"
API_VERSION = "2024-10"
BASE_URL    = f"https://{SHOP}/admin/api/{API_VERSION}"
HEADERS     = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

# ─── Optimized SEO — handle: [title (≤70 chars), description (≤160 chars)] ───
SEO_UPDATES = {
    "womens-handbags-accessories": [
        "Women's Handbags & Accessories | Totes, Crossbody | MeeeShop",
        "Shop women's handbags, crossbody bags, totes & accessories at MeeeShop. Trendy styles starting at $19.99. Free US shipping on qualifying orders.",
    ],
    "womens-curvy-plus-size-clothing": [
        "Women's Plus Size Clothing | Curvy Fashion 1X-3X | MeeeShop",
        "Stylish plus size clothing for curvy women. Dresses, jeans, tops & more in sizes 1X–3X. Judy Blue, HYFVE & more brands. Free US shipping available.",
    ],
    "made-in-usa": [
        "Made in USA Women's Clothing | American-Made Fashion | MeeeShop",
        "Shop American-made women's clothing at MeeeShop. Quality tops, dresses & bottoms crafted in the USA. Supporting domestic fashion. Free US shipping.",
    ],
    "hyfve-womens-clothing": [
        "HYFVE Women's Clothing | Tops, Dresses & Sets | MeeeShop",
        "Shop HYFVE women's clothing at MeeeShop. Trendy tops, dresses, camis & sets starting at $29.99. Free US shipping on qualifying orders. New arrivals daily.",
    ],
    "pol-womens-clothing-collection": [
        "POL Women's Clothing | Boho Tops, Blouses & Tanks | MeeeShop",
        "Shop POL women's clothing at MeeeShop. Bohemian-inspired tops, blouses, tanks & more. Unique details & quality pieces. Free US shipping available.",
    ],
    "risen-womens-jeans-collection": [
        "RISEN Women's Jeans | Skinny, Flare & Straight | MeeeShop",
        "Shop RISEN women's jeans at MeeeShop. Skinny, flare, straight & distressed styles. Flattering fits in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "judy-blue-womens-jeans": [
        "Judy Blue Jeans for Women | High Waist Tummy Control | MeeeShop",
        "Shop Judy Blue women's jeans at MeeeShop. High-waist, tummy control, flare & straight styles. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-sweaters": [
        "Women's Sweaters | Cozy Knit & Pullover Styles | MeeeShop",
        "Shop women's sweaters at MeeeShop. Cozy knit pullovers, cardigans & turtlenecks in trendy colors. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-camis-tanks": [
        "Women's Camis & Tank Tops | Ribbed, Lace & More | MeeeShop",
        "Shop women's camis & tank tops at MeeeShop. Ribbed, lace-trim, spaghetti strap & layering styles starting at $12.99. Free US shipping available.",
    ],
    "womens-t-shirts": [
        "Women's T-Shirts | Graphic Tees & Basic Tops | MeeeShop",
        "Shop women's t-shirts & graphic tees at MeeeShop. Casual basics, vintage-inspired & statement styles in sizes XS–3X. Free US shipping available.",
    ],
    "womens-shirts": [
        "Women's Shirts | Button-Down, Flowy & Casual Tops | MeeeShop",
        "Shop women's shirts at MeeeShop. Button-down, flowy, plaid & casual styles for every occasion. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-tops": [
        "Women's Tops | Trendy Blouses, Tanks & Tees | MeeeShop",
        "Shop 200+ women's tops at MeeeShop. Trendy blouses, tanks, tees & statement styles. Brands like HYFVE, POL & Umgee. Free US shipping available.",
    ],
    "womens-outerwear": [
        "Women's Outerwear | Jackets, Coats & Vests | MeeeShop",
        "Shop women's outerwear at MeeeShop. Puffer jackets, denim coats, vests & more in sizes XS–3X. Stay stylish all season. Free US shipping available.",
    ],
    "womens-dresses": [
        "Women's Dresses | Casual, Maxi, Midi & Cocktail | MeeeShop",
        "Shop 140+ women's dresses at MeeeShop. Casual, maxi, midi, cocktail & boho styles. Brands like Emory Park & Flying Tomato. Free US shipping available.",
    ],
    "womens-bottoms": [
        "Women's Bottoms | Jeans, Pants, Skirts & Shorts | MeeeShop",
        "Shop women's bottoms at MeeeShop. Jeans, pants, leggings, skirts & shorts in sizes XS–3X. Top brands & new arrivals daily. Free US shipping available.",
    ],
    "womens-rompers-jumpsuit-sets": [
        "Women's Rompers, Jumpsuits & Sets | One-Piece Styles | MeeeShop",
        "Shop women's rompers, jumpsuits & coordinating sets at MeeeShop. Trendy one-piece outfits for every occasion. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-hoodies": [
        "Women's Hoodies | Pullover & Zip-Up Cozy Styles | MeeeShop",
        "Shop women's hoodies at MeeeShop. Cozy pullover & zip-up hoodies in solid colors & prints. Sizes XS–3X. Perfect for layering. Free US shipping available.",
    ],
    "womens-sweatshirts": [
        "Women's Sweatshirts | Crewneck & Oversized Styles | MeeeShop",
        "Shop women's sweatshirts at MeeeShop. Cozy crewneck, oversized & graphic sweatshirts starting at $24.99. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-casual-dresses": [
        "Women's Casual Dresses | Comfy Everyday Styles | MeeeShop",
        "Shop women's casual dresses at MeeeShop. Comfortable everyday styles in floral, solid & boho prints. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-maxi-dresses": [
        "Women's Maxi Dresses | Flowy Long Boho Styles | MeeeShop",
        "Shop women's maxi dresses at MeeeShop. Flowy, bohemian & elegant long dresses for every occasion. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-cocktail-dresses": [
        "Women's Cocktail Dresses | Party & Date Night | MeeeShop",
        "Shop women's cocktail dresses at MeeeShop. Chic party dresses, date night styles & formal-casual looks. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-skirts": [
        "Women's Skirts | Mini, Midi & Maxi Styles | MeeeShop",
        "Shop women's skirts at MeeeShop. Mini, midi & maxi skirts in floral, denim & solid styles. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "womens-pants-leggings": [
        "Women's Pants & Leggings | Wide Leg & Straight | MeeeShop",
        "Shop women's pants & leggings at MeeeShop. Wide leg, straight, cargo & athletic leggings in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-shorts": [
        "Women's Shorts | Denim, Biker & Casual Styles | MeeeShop",
        "Shop women's shorts at MeeeShop. Denim cutoffs, biker shorts, linen & casual styles. Sizes XS–3X. Perfect for warm weather. Free US shipping available.",
    ],
    "womens-rompers": [
        "Women's Rompers | Casual & Dressy One-Piece Outfits | MeeeShop",
        "Shop women's rompers at MeeeShop. Casual, floral, denim & dressy rompers for every occasion. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-jeans": [
        "Women's Jeans | Skinny, Flare, Straight & Wide Leg | MeeeShop",
        "Shop women's jeans at MeeeShop. Judy Blue, RISEN & more — skinny, flare, wide leg & straight styles. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-new-collection": [
        "New Women's Clothing Arrivals | Latest Styles | MeeeShop",
        "Shop the newest women's clothing arrivals at MeeeShop. Fresh tops, dresses, jeans & accessories added daily. Sizes XS–3X. Free US shipping available.",
    ],
    "new-collection": [
        "New Women's Clothing Arrivals | Latest Styles | MeeeShop",
        "Shop the newest women's clothing arrivals at MeeeShop. Fresh tops, dresses, jeans & accessories added daily. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-best-selling-collection": [
        "Best Selling Women's Clothing | Top-Rated Styles | MeeeShop",
        "Shop MeeeShop's best-selling women's clothing. Customer-favorite tops, dresses, jeans & accessories. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "best-selling": [
        "Best Selling Women's Clothing | Top-Rated Styles | MeeeShop",
        "Shop MeeeShop's best-selling women's clothing. Customer-favorite tops, dresses, jeans & accessories. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-outfit-sets": [
        "Women's Matching Outfit Sets | Two-Piece Coord Sets | MeeeShop",
        "Shop women's matching outfit sets at MeeeShop. Coordinating two-piece sets in tops & bottoms, joggers & more. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-sweatshirts-hoodies": [
        "Women's Sweatshirts & Hoodies | Cozy Styles | MeeeShop",
        "Shop women's sweatshirts & hoodies at MeeeShop. Crewneck, pullover & zip-up styles in cozy fabrics. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-luxe-apparel": [
        "Women's Luxe Apparel | Elevated Everyday Styles | MeeeShop",
        "Shop women's luxe apparel at MeeeShop. Elevated fabrics, refined silhouettes & polished styles for the modern woman. Free US shipping available.",
    ],
    "womens-blazers-vests-jackets": [
        "Women's Blazers, Vests & Jackets | Work & Casual | MeeeShop",
        "Shop women's blazers, vests & jackets at MeeeShop. Tailored blazers, utility vests & casual jackets. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-blouses": [
        "Women's Blouses | Flowy, Puff Sleeve & Boho Styles | MeeeShop",
        "Shop women's blouses at MeeeShop. Flowy, puff sleeve, embroidered & boho-inspired styles. Brands like Umgee & POL. Free US shipping available.",
    ],
    "emory-park-womens-clothing": [
        "Emory Park Women's Clothing | Dresses & Tops | MeeeShop",
        "Shop Emory Park women's clothing at MeeeShop. Trendy dresses, tops & sets with unique details. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "jade-by-jane-womens-clothing": [
        "Jade By Jane Women's Clothing | Boho & Chic | MeeeShop",
        "Shop Jade By Jane women's clothing at MeeeShop. Bohemian-inspired tops, dresses & sets with feminine details. Free US shipping on qualifying orders.",
    ],
    "artemis-vintage-womens-jeans": [
        "Artemis Vintage Women's Jeans | Retro Denim | MeeeShop",
        "Shop Artemis Vintage women's jeans at MeeeShop. Retro-inspired flare, straight & wide-leg denim styles. Sizes XS–3X. Free US shipping available.",
    ],
    "fall-clothing-for-women": [
        "Fall Clothing for Women | Cozy Seasonal Styles | MeeeShop",
        "Shop women's fall clothing at MeeeShop. Sweaters, hoodies, flannels & seasonal layers in sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "puff-sleeve-tops": [
        "Women's Puff Sleeve Tops | Trendy Statement Blouses | MeeeShop",
        "Shop women's puff sleeve tops at MeeeShop. Trendy bubble sleeve blouses & statement tops. Sizes XS–3X. New arrivals weekly. Free US shipping.",
    ],
    "short-sleeve-tops": [
        "Women's Short Sleeve Tops | Casual & Dressy Styles | MeeeShop",
        "Shop women's short sleeve tops at MeeeShop. T-shirts, blouses & casual tees in sizes XS–3X. Hundreds of styles starting at $12.99. Free US shipping.",
    ],
    "long-sleeve-tops": [
        "Women's Long Sleeve Tops | Blouses, Tees & More | MeeeShop",
        "Shop women's long sleeve tops at MeeeShop. Layering tees, flowy blouses & cozy knits in sizes XS–3X. New arrivals daily. Free US shipping available.",
    ],
    "v-neck-tops": [
        "Women's V-Neck Tops | Flattering Everyday Styles | MeeeShop",
        "Shop women's v-neck tops at MeeeShop. Flattering v-neck blouses, tees & camis in sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "midi-dresses": [
        "Women's Midi Dresses | Knee-Length Boho & Casual | MeeeShop",
        "Shop women's midi dresses at MeeeShop. Knee-to-calf length floral, boho & casual styles in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "mini-dresses": [
        "Women's Mini Dresses | Short & Flirty Party Styles | MeeeShop",
        "Shop women's mini dresses at MeeeShop. Short, flirty & trendy mini dresses for date night or everyday wear. Sizes XS–3X. Free US shipping available.",
    ],
    "umgee-usa-womens-clothing": [
        "Umgee USA Women's Clothing | Boho Tops & Dresses | MeeeShop",
        "Shop Umgee USA women's clothing at MeeeShop. Bohemian blouses, embroidered tops, flowy dresses & more. Free US shipping on qualifying orders.",
    ],
    "flare-jeans": [
        "Women's Flare Jeans | Bell Bottom & 70s Denim | MeeeShop",
        "Shop women's flare jeans at MeeeShop. Bell bottom, high-waist & 70s-inspired flare denim. Judy Blue, RISEN & more. Sizes XS–3X. Free US shipping.",
    ],
    "wide-leg-jeans": [
        "Women's Wide Leg Jeans | High Waist Relaxed Denim | MeeeShop",
        "Shop women's wide leg jeans at MeeeShop. High-waist, relaxed & barrel-leg denim styles. Judy Blue & RISEN. Sizes XS–3X. Free US shipping available.",
    ],
    "straight-leg-jeans": [
        "Women's Straight Leg Jeans | Classic Rigid Denim | MeeeShop",
        "Shop women's straight leg jeans at MeeeShop. Classic rigid & magic denim straight-cut styles. Judy Blue, RISEN & more. Sizes XS–3X. Free US shipping.",
    ],
    # ── Additional Brand Collections ─────────────────────────────────────────
    "acting-pro-womens-clothing-collection-us-meeeshop": [
        "Acting Pro Women's Clothing | Tops, Dresses & More | MeeeShop",
        "Shop Acting Pro women's clothing at MeeeShop. Trendy tops, dresses & sets for everyday style. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "adora-womens-clothing": [
        "ADORA Women's Clothing | Stylish Tops & Dresses | MeeeShop",
        "Shop ADORA women's clothing at MeeeShop. Chic tops, dresses & bottoms for the modern woman. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "aemi-co": [
        "Aemi + Co Women's Clothing | Trendy Styles | MeeeShop",
        "Shop Aemi + Co women's clothing at MeeeShop. Trendy tops, dresses & more in sizes XS–3X. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "american-bazi": [
        "AMERICAN BAZI Women's Clothing | Casual & Chic Styles | MeeeShop",
        "Shop AMERICAN BAZI women's clothing at MeeeShop. Casual-chic tops, dresses & sets. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "amoli": [
        "Amoli Women's Clothing | Feminine Tops & Dresses | MeeeShop",
        "Shop Amoli women's clothing at MeeeShop. Feminine tops, dresses & blouses in sizes XS–3X. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "andthewhy-clothing": [
        "AND THE WHY Women's Clothing | Boho & Casual Styles | MeeeShop",
        "Shop AND THE WHY women's clothing at MeeeShop. Boho-inspired tops, dresses & sets. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "anniewear-womens-clothing": [
        "ANNIEWEAR Women's Clothing | Tops, Blouses & Sets | MeeeShop",
        "Shop ANNIEWEAR women's clothing at MeeeShop. Stylish tops, blouses & coordinating sets. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "artini-accessories": [
        "Artini Women's Accessories | Bags, Jewelry & More | MeeeShop",
        "Shop Artini women's accessories at MeeeShop. Trendy bags, jewelry & fashion accessories. New styles weekly. Free US shipping on qualifying orders.",
    ],
    "bibi-womens-clothing": [
        "BIBI Women's Clothing | Casual & Chic Fashion | MeeeShop",
        "Shop BIBI women's clothing at MeeeShop. Casual-chic tops, dresses & bottoms in sizes XS–3X. Free US shipping on qualifying orders. Shop now!",
    ],
    "bombom-usa": [
        "BOMBOM USA Women's Clothing | Loungewear & Sets | MeeeShop",
        "Shop BOMBOM USA women's clothing at MeeeShop. Cozy loungewear, matching sets & casual styles. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "celeste-clothing": [
        "CELESTE Women's Clothing | Feminine & Trendy Styles | MeeeShop",
        "Shop CELESTE women's clothing at MeeeShop. Feminine tops, dresses & sets in sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "culture-code-womens-clothing": [
        "Culture Code Women's Clothing | Elevated Casual Styles | MeeeShop",
        "Shop Culture Code women's clothing at MeeeShop. Elevated casual tops, dresses & sets. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "davi-dani-womens-apparel": [
        "DAVI & DANI Women's Clothing | Tops, Dresses & More | MeeeShop",
        "Shop DAVI & DANI women's clothing at MeeeShop. Stylish tops, dresses & blouses in sizes XS–3X. Free US shipping on qualifying orders. Shop now!",
    ],
    "e-luna-womens-clothing": [
        "e Luna Women's Clothing | Boho Tops & Dresses | MeeeShop",
        "Shop e Luna women's clothing at MeeeShop. Bohemian-inspired tops, dresses & more in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "fame-accessories": [
        "FAME Women's Accessories | Bags, Belts & Jewelry | MeeeShop",
        "Shop FAME women's accessories at MeeeShop. Trendy bags, belts, jewelry & fashion accessories. Free US shipping on qualifying orders. Shop now!",
    ],
    "flying-monkey-womens-jeans-collection": [
        "Flying Monkey Women's Jeans | Distressed Denim | MeeeShop",
        "Shop Flying Monkey women's jeans at MeeeShop. Distressed, flare, straight & wide-leg denim. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "gilli-womens-clothing-collection": [
        "Gilli Women's Clothing | Flowy Tops & Dresses | MeeeShop",
        "Shop Gilli women's clothing at MeeeShop. Flowy, feminine tops, dresses & blouses in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "hailey-co": [
        "Hailey & Co Women's Clothing | Trendy Fashion | MeeeShop",
        "Shop Hailey & Co women's clothing at MeeeShop. Trendy tops, dresses & sets for every occasion. Sizes XS–3X. Free US shipping available.",
    ],
    "heimish-usa-womens-clothing": [
        "HEIMISH Women's Clothing | Korean-Inspired Styles | MeeeShop",
        "Shop HEIMISH women's clothing at MeeeShop. Korean-inspired tops, dresses & sets in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "heyson-clothing": [
        "HEYSON Women's Clothing | Soft Knit Tops & Sets | MeeeShop",
        "Shop HEYSON women's clothing at MeeeShop. Ultra-soft knit tops, sets & loungewear in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "himawari-backpacks": [
        "HIMAWARI Backpacks for Women | Stylish & Functional | MeeeShop",
        "Shop HIMAWARI women's backpacks at MeeeShop. Stylish, functional backpacks for school, travel & everyday use. Free US shipping on qualifying orders.",
    ],
    "insane-gene-womens-denim": [
        "Insane Gene Women's Jeans | Trendy Denim Styles | MeeeShop",
        "Shop Insane Gene women's jeans at MeeeShop. Trendy distressed, flare & straight denim in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "justin-taylor-apparel-accessories": [
        "Justin & Taylor Women's Clothing & Accessories | MeeeShop",
        "Shop Justin & Taylor women's clothing & accessories at MeeeShop. Trendy tops, dresses & bags. Sizes XS–3X. Free US shipping available.",
    ],
    "kancan-usa-womens-jeans": [
        "KanCan Women's Jeans | Skinny, Flare & Straight | MeeeShop",
        "Shop KanCan women's jeans at MeeeShop. High-quality skinny, flare, straight & distressed denim. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "kimberly-c": [
        "Kimberly C Women's Clothing | Elegant & Chic Styles | MeeeShop",
        "Shop Kimberly C women's clothing at MeeeShop. Elegant tops, dresses & sets for every occasion. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "la-miel-womens-clothing-collection": [
        "LA MIEL Women's Clothing | Boho Tops & Dresses | MeeeShop",
        "Shop LA MIEL women's clothing at MeeeShop. Bohemian-inspired tops, dresses & blouses in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "le-lis-womens-clothing": [
        "LE LIS Women's Clothing | Feminine & Trendy Styles | MeeeShop",
        "Shop LE LIS women's clothing at MeeeShop. Feminine tops, dresses & sets with unique details. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "lilou-womens-clothing-collection": [
        "Lilou Women's Clothing | Casual & Chic Fashion | MeeeShop",
        "Shop Lilou women's clothing at MeeeShop. Casual-chic tops, dresses & blouses in sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "mittoshop-clothing": [
        "MITTOSHOP Women's Clothing | Trendy Casual Styles | MeeeShop",
        "Shop MITTOSHOP women's clothing at MeeeShop. Trendy casual tops, dresses & sets. Sizes XS–3X. New arrivals weekly. Free US shipping on qualifying orders.",
    ],
    "mustard-seed-womens-clothing": [
        "MUSTARD SEED Women's Clothing | Boho & Feminine | MeeeShop",
        "Shop MUSTARD SEED women's clothing at MeeeShop. Bohemian-inspired tops, dresses & blouses. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "ninexis-womens-clothing-collection": [
        "NINEXIS Women's Clothing | Casual Tops & Sets | MeeeShop",
        "Shop NINEXIS women's clothing at MeeeShop. Casual tops, matching sets & comfortable styles. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "oddi": [
        "ODDI Women's Clothing | Trendy & Feminine Styles | MeeeShop",
        "Shop ODDI women's clothing at MeeeShop. Trendy tops, dresses & blouses with feminine details. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "one-and-only-collective-inc-womens-clothing": [
        "ONE AND ONLY Women's Clothing | Casual & Chic | MeeeShop",
        "Shop ONE AND ONLY COLLECTIVE women's clothing at MeeeShop. Casual-chic tops, dresses & sets. Sizes XS–3X. Free US shipping available.",
    ],
    "orange-farm-womens-clothing": [
        "Orange Farm Women's Clothing | Boho & Casual Styles | MeeeShop",
        "Shop Orange Farm women's clothing at MeeeShop. Bohemian-inspired tops, dresses & more. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "p-rose": [
        "P & Rose Women's Clothing | Elegant Tops & Dresses | MeeeShop",
        "Shop P & Rose women's clothing at MeeeShop. Elegant tops, dresses & blouses for every occasion. Sizes XS–3X. Free US shipping available.",
    ],
    "petal-dew": [
        "Petal Dew Women's Clothing | Floral & Feminine Styles | MeeeShop",
        "Shop Petal Dew women's clothing at MeeeShop. Floral, feminine tops, dresses & sets. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "recycled-karma-womens-graphic-tees": [
        "Recycled Karma Graphic Tees for Women | MeeeShop",
        "Shop Recycled Karma women's graphic tees at MeeeShop. Vintage-inspired designs, distressed styles & statement tees. Sizes XS–3X. Free US shipping.",
    ],
    "vervet-by-flying-monkey-womens-jeans": [
        "VERVET by Flying Monkey Women's Jeans | MeeeShop",
        "Shop VERVET by Flying Monkey women's jeans at MeeeShop. Distressed, flare, straight & wide-leg denim. Sizes XS–3X. Free US shipping available.",
    ],
    "very-j-womens-clothing": [
        "VERY J Women's Clothing | Trendy Tops & Dresses | MeeeShop",
        "Shop VERY J women's clothing at MeeeShop. Trendy tops, dresses & blouses with feminine details. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "vibrant-miu-womens-jeans": [
        "Vibrant M.i.U Women's Jeans | Trendy Denim Styles | MeeeShop",
        "Shop Vibrant M.i.U women's jeans at MeeeShop. Trendy flare, straight & distressed denim. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "white-birch-womens-clothing": [
        "White Birch Women's Clothing | Boho & Cozy Styles | MeeeShop",
        "Shop White Birch women's clothing at MeeeShop. Bohemian-inspired tops, sweaters & dresses. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "yelete-womens-clothing": [
        "Yelete Women's Clothing | Soft Knit & Casual Styles | MeeeShop",
        "Shop Yelete women's clothing at MeeeShop. Soft knit tops, leggings & casual sets in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-womens-clothing": [
        "ZENANA Women's Clothing | Cozy Basics & Essentials | MeeeShop",
        "Shop ZENANA women's clothing at MeeeShop. Cozy basics, soft knit tops, loungewear & essentials. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-dresses": [
        "ZENANA Women's Dresses | Soft & Casual Styles | MeeeShop",
        "Shop ZENANA women's dresses at MeeeShop. Soft, casual everyday dresses in solid colors & prints. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-shorts": [
        "ZENANA Women's Shorts | Comfy Everyday Styles | MeeeShop",
        "Shop ZENANA women's shorts at MeeeShop. Comfortable everyday shorts in solid colors & fun prints. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-sweaters": [
        "ZENANA Women's Sweaters | Soft Knit & Cozy Styles | MeeeShop",
        "Shop ZENANA women's sweaters at MeeeShop. Soft knit pullovers, cardigans & cozy styles. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-sweatshirts": [
        "ZENANA Women's Sweatshirts | Cozy Crewneck Styles | MeeeShop",
        "Shop ZENANA women's sweatshirts at MeeeShop. Cozy crewneck & pullover sweatshirts in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "zenana-tops": [
        "ZENANA Women's Tops | Soft Basics & Everyday Tees | MeeeShop",
        "Shop ZENANA women's tops at MeeeShop. Soft basic tees, camis & everyday tops in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    # ── Additional Category Collections ──────────────────────────────────────
    "womens-active-bottoms": [
        "Women's Active Bottoms | Leggings, Shorts & Joggers | MeeeShop",
        "Shop women's active bottoms at MeeeShop. High-waist leggings, athletic shorts & joggers for workouts & everyday wear. Sizes XS–3X. Free US shipping.",
    ],
    "womens-active-tops": [
        "Women's Active Tops | Sports Bras & Athletic Tees | MeeeShop",
        "Shop women's active tops at MeeeShop. Sports bras, athletic tees & workout tops in sizes XS–3X. Stylish & functional. Free US shipping available.",
    ],
    "womens-activewear": [
        "Women's Activewear | Workout Outfits & Athleisure | MeeeShop",
        "Shop women's activewear at MeeeShop. Workout sets, leggings, sports bras & athleisure styles. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-bodysuits": [
        "Women's Bodysuits | Fitted & Flowy One-Piece Tops | MeeeShop",
        "Shop women's bodysuits at MeeeShop. Fitted, flowy & tuck-free bodysuit tops in sizes XS–3X. Perfect for everyday wear. Free US shipping available.",
    ],
    "womens-camis-tanks-tops": [
        "Women's Camis & Tank Tops | Ribbed, Lace & Layering | MeeeShop",
        "Shop women's camis & tank tops at MeeeShop. Ribbed, lace-trim, spaghetti strap & layering styles starting at $12.99. Free US shipping available.",
    ],
    "womens-cardigans": [
        "Women's Cardigans | Open Front & Button-Down Styles | MeeeShop",
        "Shop women's cardigans at MeeeShop. Open front, button-down & cozy knit cardigans in sizes XS–3X. Perfect for layering. Free US shipping available.",
    ],
    "womens-denim-tops-jackets": [
        "Women's Denim Tops & Jackets | Casual Denim Styles | MeeeShop",
        "Shop women's denim tops & jackets at MeeeShop. Denim button-down shirts, cropped jackets & trucker styles. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-formal-evening-dresses": [
        "Women's Formal & Evening Dresses | Elegant Styles | MeeeShop",
        "Shop women's formal & evening dresses at MeeeShop. Elegant gowns, cocktail & special occasion dresses. Sizes XS–3X. Free US shipping available.",
    ],
    "womens-hats-scarves": [
        "Women's Hats & Scarves | Trendy Accessories | MeeeShop",
        "Shop women's hats & scarves at MeeeShop. Trendy beanies, baseball caps, wide-brim hats & scarves. Free US shipping on qualifying orders.",
    ],
    "womens-jean-shorts": [
        "Women's Jean Shorts | Denim Cutoffs & Distressed | MeeeShop",
        "Shop women's jean shorts at MeeeShop. Denim cutoffs, distressed & raw-hem styles in sizes XS–3X. Perfect for summer. Free US shipping available.",
    ],
    "womens-knit-tops": [
        "Women's Knit Tops | Ribbed & Cozy Everyday Styles | MeeeShop",
        "Shop women's knit tops at MeeeShop. Ribbed, cozy & stretchy knit tops for every day. Sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "long-sleeve-dresses": [
        "Women's Long Sleeve Dresses | Fall & Winter Styles | MeeeShop",
        "Shop women's long sleeve dresses at MeeeShop. Fall & winter-ready midi, maxi & casual dresses. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "womens-lounge-set": [
        "Women's Lounge Sets | Cozy Matching Sets | MeeeShop",
        "Shop women's lounge sets at MeeeShop. Cozy matching sets in soft fabrics for lounging & casual days. Sizes XS–3X. Free US shipping available.",
    ],
    "mock-neck-tops": [
        "Women's Mock Neck Tops | Chic Everyday Styles | MeeeShop",
        "Shop women's mock neck tops at MeeeShop. Chic, flattering mock neck tees & blouses in sizes XS–3X. New arrivals weekly. Free US shipping available.",
    ],
    "womens-shoes": [
        "Women's Shoes | Boots, Sandals & Sneakers | MeeeShop",
        "Shop women's shoes at MeeeShop. Trendy boots, sandals, sneakers & flats in sizes 6–11. New styles added weekly. Free US shipping on qualifying orders.",
    ],
    "womens-sleepwear": [
        "Women's Sleepwear | Pajamas, Sets & Sleep Tops | MeeeShop",
        "Shop women's sleepwear at MeeeShop. Cozy pajama sets, sleep tops & lounge pants in sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "sweater-pullover": [
        "Women's Pullover Sweaters | Cozy Knit Styles | MeeeShop",
        "Shop women's pullover sweaters at MeeeShop. Cozy knit pullovers in solid colors & patterns. Sizes XS–3X. Perfect for layering. Free US shipping.",
    ],
    # ── Sale & Deal Collections ───────────────────────────────────────────────
    "25-percent-off": [
        "25% Off Women's Clothing | Sale Styles | MeeeShop",
        "Shop 25% off women's clothing at MeeeShop. Tops, dresses, jeans & accessories on sale. Sizes XS–3X. Free US shipping on qualifying orders. Shop now!",
    ],
    "sale-plus-size-apparel": [
        "Plus Size Women's Clothing Sale | Curvy Styles on Sale | MeeeShop",
        "Shop plus size women's clothing on sale at MeeeShop. Dresses, tops, jeans & more in sizes 1X–3X at discounted prices. Free US shipping available.",
    ],
    "selected-usa-styles": [
        "Selected USA Women's Styles | American Fashion | MeeeShop",
        "Shop selected USA women's styles at MeeeShop. Curated American-made & domestic fashion. Tops, dresses & more. Free US shipping on qualifying orders.",
    ],
    "under-40": [
        "Women's Clothing Under $40 | Affordable Fashion | MeeeShop",
        "Shop women's clothing under $40 at MeeeShop. Stylish tops, dresses, jeans & more under $40. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "under-50": [
        "Women's Clothing Under $50 | Budget-Friendly Styles | MeeeShop",
        "Shop women's clothing under $50 at MeeeShop. Trendy tops, dresses, jeans & accessories under $50. Sizes XS–3X. Free US shipping available.",
    ],
    "usa-sale": [
        "Women's Clothing Sale | Shop Sale Styles | MeeeShop",
        "Shop women's clothing sale at MeeeShop. Save on tops, dresses, jeans & accessories. Sizes XS–3X. New sale items added regularly. Free US shipping.",
    ],
    "holiday-outfit-ideas": [
        "Holiday Outfit Ideas for Women | Festive Fashion | MeeeShop",
        "Shop holiday outfit ideas for women at MeeeShop. Festive dresses, tops & accessories for parties & celebrations. Sizes XS–3X. Free US shipping.",
    ],
    "christmas-gift-collection": [
        "Christmas Gifts for Women | Fashion Gift Ideas | MeeeShop",
        "Shop Christmas gifts for women at MeeeShop. Tops, dresses, accessories & more — perfect for gifting. Sizes XS–3X. Free US shipping on qualifying orders.",
    ],
    "beauty-essentials": [
        "Beauty Essentials for Women | Skincare & Beauty Picks | MeeeShop",
        "Shop beauty essentials for women at MeeeShop. Skincare, haircare & beauty must-haves to complement your wardrobe. Free US shipping on qualifying orders.",
    ],
    "black-friday-chic-trendy-womens-fashion-deals-discounts": [
        "Black Friday Women's Fashion Deals | MeeeShop Sale",
        "Shop Black Friday women's fashion deals at MeeeShop. Chic tops, dresses, jeans & accessories at discounted prices. Sizes XS–3X. Free US shipping.",
    ],
}


def slugify(s):
    s = s.lower()
    s = re.sub(r"['’&,]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def api_get(url, params=None):
    for attempt in range(4):
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 429:
            wait = int(float(r.headers.get("Retry-After", 4)))
            print(f"    Rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"GET failed after retries: {url}")


def api_put(url, payload):
    for attempt in range(4):
        r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
        if r.status_code == 429:
            wait = int(float(r.headers.get("Retry-After", 4)))
            print(f"    Rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"PUT failed after retries: {url}")


def api_post(url, payload):
    for attempt in range(4):
        r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if r.status_code == 429:
            wait = int(float(r.headers.get("Retry-After", 4)))
            print(f"    Rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue
        return r
    raise RuntimeError(f"POST failed after retries: {url}")


def set_seo_metafields(collection_id, seo_title, seo_desc):
    """Set title_tag and description_tag metafields on a collection.
    Uses POST to create; if 422 (already exists), GETs the existing ID and PUTs."""
    for key, value in [("title_tag", seo_title), ("description_tag", seo_desc)]:
        mf_url  = f"{BASE_URL}/collections/{collection_id}/metafields.json"
        payload = {"metafield": {"namespace": "global", "key": key, "value": value, "type": "single_line_text_field"}}
        r = api_post(mf_url, payload)
        if r.status_code == 201:
            continue  # created successfully
        if r.status_code == 422:
            # Already exists — fetch its ID and update it
            existing = api_get(mf_url, {"namespace": "global", "key": key, "fields": "id"})
            mfs = existing.json().get("metafields", [])
            if mfs:
                mf_id = mfs[0]["id"]
                api_put(f"{BASE_URL}/metafields/{mf_id}.json", {"metafield": {"id": mf_id, "value": value}})
        else:
            r.raise_for_status()


def fetch_all(collection_type):
    key = f"{collection_type}_collections"
    url = f"{BASE_URL}/{key}.json"
    params = {
        "limit": 250,
        "fields": "id,title,handle",
    }
    results = []
    while url:
        r = api_get(url, params)
        results.extend(r.json().get(key, []))
        link = r.headers.get("Link", "")
        url, params = None, None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.strip().split(";")[0].strip().strip("<>")
                break
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 62)
    print("  MeeeShop SEO Updater -- Collections")
    print("=" * 62)

    # 1. Fetch
    print("\n[1/4] Fetching collections...")
    custom = fetch_all("custom")
    smart  = fetch_all("smart")
    all_cols = [(c, "custom") for c in custom] + [(c, "smart") for c in smart]
    print(f"      {len(custom)} custom + {len(smart)} smart = {len(all_cols)} total")

    # 2. Backup — fetch current metafields for each collection
    print("\n[2/4] Saving backup (fetching current metafields)...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_rows = []
    for c, t in all_cols:
        mf_url = f"{BASE_URL}/collections/{c['id']}/metafields.json"
        existing = api_get(mf_url, {"namespace": "global", "fields": "key,value"}).json().get("metafields", [])
        mf_map = {m["key"]: m["value"] for m in existing}
        backup_rows.append({
            "id": c["id"], "type": t, "title": c["title"], "handle": c["handle"],
            "seo_title": mf_map.get("title_tag", ""),
            "seo_description": mf_map.get("description_tag", ""),
        })
        time.sleep(0.3)
    backup = {"timestamp": ts, "total": len(all_cols), "collections": backup_rows}
    backup_file = f"seo_backup_{ts}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
    print(f"      Saved -> {backup_file}")

    # 3. Match
    print("\n[3/4] Matching to SEO updates...")
    to_update, skipped = [], []
    for col, ctype in all_cols:
        handle = col["handle"]
        title  = col["title"]
        if handle in SEO_UPDATES:
            to_update.append((col, ctype, SEO_UPDATES[handle], "handle"))
        else:
            slug = slugify(title)
            match = SEO_UPDATES.get(slug)
            if match:
                to_update.append((col, ctype, match, "title"))
            else:
                skipped.append((handle, title))
    print(f"      Matched: {len(to_update)}  |  Unmatched: {len(skipped)}")

    # 4. Update via Metafields API
    print(f"\n[4/4] Applying updates via Metafields API...\n")
    success, errors = 0, []
    for col, ctype, (seo_title, seo_desc), match_by in to_update:
        cid  = col["id"]
        name = col["title"]
        try:
            set_seo_metafields(cid, seo_title, seo_desc)
            print(f"  OK  {name}")
            success += 1
        except Exception as e:
            print(f"  FAIL  {name}  ->  {e}")
            errors.append(name)
        time.sleep(0.6)

    # Summary
    print(f"\n{'=' * 62}")
    print(f"  COMPLETE  --  {success} updated  |  {len(errors)} errors  |  {len(skipped)} unmatched")
    if skipped:
        print(f"\n  Collections with no SEO mapping (add them to SEO_UPDATES):")
        for h, t in skipped:
            print(f"    handle={h!r}   title={t!r}")
    if errors:
        print(f"\n  Failed updates:")
        for t in errors: print(f"    - {t}")
    print(f"\n  Backup: {backup_file}")
    print("=" * 62)


if __name__ == "__main__":
    main()
