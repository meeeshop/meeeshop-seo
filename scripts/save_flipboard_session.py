#!/usr/bin/env python3
"""
save_flipboard_session.py — Bypass CAPTCHAs by authenticating locally and saving the state.

This script opens a visible browser. You log into Flipboard manually (solving
any Captchas). Once logged in, it extracts the browser cookies/session and 
saves it double-encrypted into `secrets.enc` as FLIPBOARD_SESSION.

Usage:
  python scripts/save_flipboard_session.py
"""
import os
import sys
import json
import argparse
import time
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
except ImportError:
    sys.exit("Selenium not installed. Run: pip install selenium webdriver-manager")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secrets_manager import _get_keys, get_secret
from cryptography.fernet import Fernet

def encrypt_value(value: str, primary: bytes, fallback: bytes) -> str:
    inner = Fernet(fallback).encrypt(value.encode("utf-8"))
    return Fernet(primary).encrypt(inner).decode("utf-8")

def run():
    print("\n" + "="*60)
    print("  Flipboard Session Saver")
    print("="*60 + "\n")
    
    email = ""
    try:
        email = get_secret("FLIPBOARD_EMAIL")
    except Exception:
        pass

    print("Launching a visible browser...")
    print("Please log into Flipboard. Solve any CAPTCHAs if prompted.")
    
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Override webdriver flag to hide automation fingerprint
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    driver.get("https://flipboard.com/signin")
    
    if email:
        try:
            time.sleep(2)
            email_loc = driver.find_element(By.CSS_SELECTOR, 'input[name="username"], input[type="email"]')
            email_loc.send_keys(email)
            print(f"Pre-filled email: {email}")
        except Exception:
            pass
    
    print("\nWaiting for you to successfully log in...")
    print("Solve any CAPTCHAs if prompted.")
    
    input("\nPress ENTER here in your terminal ONLY AFTER you have successfully logged in and see your feed...")

    print("\n✅ Login detected! Extracting session state...")
    cookies = driver.get_cookies()
    driver.quit()

    print("Encrypting session cookies and saving to vault...")
    primary, fallback = _get_keys()
    enc_file = ROOT / "secrets.enc"
    
    if enc_file.exists():
        with open(enc_file, "r", encoding="utf-8") as f:
            vault = json.load(f)
    else:
        vault = {}
        
    state_json = json.dumps(cookies)
    vault["FLIPBOARD_SESSION"] = encrypt_value(state_json, primary, fallback)
    
    with open(enc_file, "w", encoding="utf-8") as f:
        json.dump(vault, f, indent=2)
        
    print(f"\n🎉 Session saved successfully to {enc_file.name}")
    print("You can now commit and push `secrets.enc` to your remote branch.")
    print("GitHub Actions will use this session to bypass Captchas automatically!")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Save Flipboard session cookies to bypass CAPTCHAs.")
    ap.add_argument("--primary", help="Primary encryption key (optional if in .env)")
    ap.add_argument("--fallback", help="Fallback encryption key (optional if in .env)")
    args = ap.parse_args()

    if args.primary:
        os.environ["ENCRYPTION_KEY_PRIMARY"] = args.primary
    if args.fallback:
        os.environ["ENCRYPTION_KEY_FALLBACK"] = args.fallback

    run()