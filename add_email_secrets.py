import json
import sys
import getpass
from pathlib import Path
from cryptography.fernet import Fernet

# Import your existing key loader
from secrets_manager import _get_keys

def double_encrypt(plaintext: str, fernet_primary: Fernet, fernet_fallback: Fernet) -> str:
    inner = fernet_fallback.encrypt(plaintext.encode('utf-8'))
    outer = fernet_primary.encrypt(inner)
    return outer.decode()

def main():
    print("=== Add SMTP Secrets to secrets.enc ===")
    
    # Load encryption keys. Prefer .env, but fall back to interactive entry to avoid persisting keys.
    try:
        primary, fallback = _get_keys()
        # Validate keys right after getting them. If invalid, treat as not found.
        if primary:
            Fernet(primary)
        if fallback:
            Fernet(fallback)
    except Exception as e:
        print(f"🔑 Could not load keys from environment ({e}), falling back to interactive entry.")
        primary = fallback = None

    if not primary or not fallback:
        print("\n🔑 Encryption keys not found or invalid in environment. Please enter them now (they will NOT be saved).")
        while True:
            primary_input = input("Enter ENCRYPTION_KEY_PRIMARY (base64 32-byte) or press Enter to generate a new key: ").strip()
            fallback_input = input("Enter ENCRYPTION_KEY_FALLBACK (base64 32-byte) or press Enter to generate a new key: ").strip()
            try:
                # If user leaves input blank, generate a fresh Fernet key
                if not primary_input:
                    generated = Fernet.generate_key()
                    print(f"🔑 Generated ENCRYPTION_KEY_PRIMARY: {generated.decode()}")
                    primary_input = generated.decode()
                if not fallback_input:
                    generated = Fernet.generate_key()
                    print(f"🔑 Generated ENCRYPTION_KEY_FALLBACK: {generated.decode()}")
                    fallback_input = generated.decode()
                # Validate keys by creating Fernet instances
                Fernet(primary_input.encode())
                Fernet(fallback_input.encode())
                primary = primary_input.encode()
                fallback = fallback_input.encode()
                break
            except Exception as e:
                print(f"❌ Invalid key(s): {e}. Please try again.")

    # At this point both `primary` and `fallback` are guaranteed to be set.
    # Create Fernet objects for encryption/decryption.
    fernet_primary = Fernet(primary)
    fernet_fallback = Fernet(fallback)

    vault_path = Path(__file__).parent / "secrets.enc"
    vault = {}
    if vault_path.exists():
        with open(vault_path, "r", encoding="utf-8") as f:
            vault = json.load(f)

    print("\nEnter your SMTP details (leave blank to keep existing):")
    fields = ["SMTP_SERVER", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "FROM_EMAIL"]
    
    updates = 0
    for field in fields:
        val = input(f"{field}: ").strip()
        if val:
            try:
                vault[field] = double_encrypt(val, fernet_primary, fernet_fallback)
                updates += 1
            except Exception as e:
                print(f"\n❌ Error encrypting {field}: {e}")
                sys.exit(1)
            
    if updates > 0:
        with open(vault_path, "w", encoding="utf-8") as f:
            json.dump(vault, f, indent=2)
        print(f"\n✅ Successfully added {updates} new encrypted keys to secrets.enc")
    else:
        print("\nNo updates made.")

if __name__ == "__main__":
    main()