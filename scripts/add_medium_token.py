#!/usr/bin/env python3
"""
add_medium_token.py — Utility to securely inject your Medium Token into secrets.enc

Usage:
  python scripts/add_medium_token.py --token "YOUR_MEDIUM_TOKEN"
"""
import os
import sys
import json
import argparse
from pathlib import Path
from cryptography.fernet import Fernet

# Import key loader directly from your active secrets manager
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secrets_manager import _get_keys

def add_token(new_token: str):
    primary, fallback = _get_keys()
    enc_file = ROOT / "secrets.enc"
    
    if enc_file.exists():
        with open(enc_file, "r", encoding="utf-8") as f:
            vault = json.load(f)
    else:
        vault = {}
        
    # Double-Fernet encrypt (Fallback -> Primary) to match decryption
    inner = Fernet(fallback).encrypt(new_token.encode("utf-8"))
    ciphertext = Fernet(primary).encrypt(inner).decode("utf-8")
    
    vault["MEDIUM_INTEGRATION_TOKEN"] = ciphertext
        
    with open(enc_file, "w", encoding="utf-8") as f:
        json.dump(vault, f, indent=2)
        
    print(f"Successfully added MEDIUM_INTEGRATION_TOKEN to {enc_file.name}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True, help="Medium Integration Token")
    ap.add_argument("--primary", help="Primary encryption key (optional if in .env)")
    ap.add_argument("--fallback", help="Fallback encryption key (optional if in .env)")
    args = ap.parse_args()
    
    if args.primary: os.environ["ENCRYPTION_KEY_PRIMARY"] = args.primary
    if args.fallback: os.environ["ENCRYPTION_KEY_FALLBACK"] = args.fallback
    
    add_token(args.token)
    