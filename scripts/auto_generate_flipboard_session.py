#!/usr/bin/env python3
"""
auto_generate_flipboard_session.py — Automatically log into Flipboard, save cookies to secrets.enc
"""
import os
import sys
import json
import time
import logging
from pathlib import Path
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.secrets_manager import _get_keys, get_secret
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def encrypt_value(value: str, primary: bytes, fallback: bytes) -> str:
    inner = Fernet(fallback).encrypt(value.encode("utf-8"))
    return Fernet(primary).encrypt(inner).decode("utf-8")

def main():
    email = get_secret("FLIPBOARD_EMAIL")
    password = get_secret("FLIPBOARD_PASSWORD")
    
    logging.info(f"Authenticating into Flipboard as: {email}")

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    try:
        driver.get("https://flipboard.com/signin")
        time.sleep(3)
        
        logging.info("Searching for email input field...")
        try:
            email_loc = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
            )
        except Exception:
            logging.info("Looking for Email Sign-in button...")
            try:
                email_btn = driver.find_element(By.XPATH, '//*[(self::button or self::a) and (contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "email") or contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "log in"))]')
                driver.execute_script("arguments[0].click();", email_btn)
                time.sleep(1)
            except Exception as e:
                logging.warning(f"Could not click email button: {e}")
            email_loc = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
            )
            
        driver.execute_script("arguments[0].click();", email_loc)
        time.sleep(0.5)
        for char in email:
            email_loc.send_keys(char)
            time.sleep(0.05)
            
        time.sleep(1)
        pass_loc = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="password"], input[type="password"]'))
        )
        driver.execute_script("arguments[0].click();", pass_loc)
        time.sleep(0.5)
        for char in password:
            pass_loc.send_keys(char)
            time.sleep(0.05)
            
        time.sleep(1)
        submit_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        driver.execute_script("arguments[0].click();", submit_btn)
        
        logging.info("Submitted login form. Waiting for authentication confirmation...")
        time.sleep(5)
        
        # Check if login succeeded
        logged_in = False
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
            )
            logged_in = True
        except Exception:
            if "signin" not in driver.current_url.lower():
                logged_in = True
                
        if logged_in:
            logging.info("✅ Login successful! Extracting cookies...")
            cookies = driver.get_cookies()
            state_json = json.dumps(cookies)
            
            primary, fallback = _get_keys()
            enc_file = ROOT / "secrets.enc"
            
            with open(enc_file, "r", encoding="utf-8") as f:
                vault = json.load(f)
                
            vault["FLIPBOARD_SESSION"] = encrypt_value(state_json, primary, fallback)
            
            with open(enc_file, "w", encoding="utf-8") as f:
                json.dump(vault, f, indent=2)
                
            logging.info(f"🎉 Saved {len(cookies)} session cookies to {enc_file.name}")
            
            # Verify decryption
            session_test = get_secret("FLIPBOARD_SESSION")
            parsed = json.loads(session_test)
            logging.info(f"Verified decryption of FLIPBOARD_SESSION with {len(parsed)} cookies.")
        else:
            logging.error(f"❌ Login failed. Current URL: {driver.current_url}")
            driver.save_screenshot("auto_login_failure.png")
            sys.exit(1)
            
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
