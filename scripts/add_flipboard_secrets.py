#!/usr/bin/env python3
"""
add_flipboard_secrets.py — Utility to securely inject Flipboard credentials into secrets.enc

Usage:
  python scripts/add_flipboard_secrets.py \
      --email "your_email@example.com" \
      --password "your_password" \
      --magazine "MeeeShop Style Guide"
"""
import os
import sys
import json
import argparse
from pathlib import Path
from cryptography.fernet import Fernet

# Assumes secrets_manager.py is in the same 'scripts' directory
ROOT = Path(__file__).resolve().parent.parent
from secrets_manager import _get_keys

def encrypt_value(value: str, primary: bytes, fallback: bytes) -> str:
    """Double-Fernet encrypt (Fallback -> Primary) to match decryption."""
    inner = Fernet(fallback).encrypt(value.encode("utf-8"))
    return Fernet(primary).encrypt(inner).decode("utf-8")

def add_secrets(email: str, password: str, magazine: str):
    primary, fallback = _get_keys()
    enc_file = ROOT / "secrets.enc"
    
    if enc_file.exists():
        with open(enc_file, "r", encoding="utf-8") as f:
            vault = json.load(f)
    else:
        vault = {}
        
    if email:
        vault["FLIPBOARD_EMAIL"] = encrypt_value(email, primary, fallback)
    if password:
        vault["FLIPBOARD_PASSWORD"] = encrypt_value(password, primary, fallback)
    if magazine:
        vault["FLIPBOARD_MAGAZINE"] = encrypt_value(magazine, primary, fallback)
        
    with open(enc_file, "w", encoding="utf-8") as f:
        json.dump(vault, f, indent=2)
        
    print(f"Successfully added Flipboard credentials to {enc_file.name}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="Flipboard Email")
    ap.add_argument("--password", required=True, help="Flipboard Password")
    ap.add_argument("--magazine", default="MeeeShop Style Guide", help="Flipboard Magazine Name")
    ap.add_argument("--primary", help="Primary encryption key (optional if in .env)")
    ap.add_argument("--fallback", help="Fallback encryption key (optional if in .env)")
    args = ap.parse_args()
    
    if args.primary: os.environ["ENCRYPTION_KEY_PRIMARY"] = args.primary
    if args.fallback: os.environ["ENCRYPTION_KEY_FALLBACK"] = args.fallback
    
    add_secrets(args.email, args.password, args.magazine)