@echo off
cd /d "C:\Users\USER\Downloads\Shopify_Claude"
echo [%DATE% %TIME%] Starting MeeeShop YouTube Shorts automation... >> youtube_daily.log
python -u youtube_shorts.py >> youtube_daily.log 2>&1
echo [%DATE% %TIME%] Run complete. >> youtube_daily.log
