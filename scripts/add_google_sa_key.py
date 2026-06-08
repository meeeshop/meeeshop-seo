#!/usr/bin/env python3
"""
add_google_sa_key.py — Inject Google Service Account JSON key into secrets.enc
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Encrypts the entire Google SA JSON key using the same double-Fernet scheme as
the rest of the vault:
    Fernet(PRIMARY).encrypt( Fernet(FALLBACK).encrypt( json_string ) )

Adds it as key "GOOGLE_SA_KEY_JSON" inside secrets.enc.

Usage (keys from .env):
    python scripts/add_google_sa_key.py --key-file google_sa_key.json

Usage (keys passed directly — use for one-shot CI bootstrap):
    python scripts/add_google_sa_key.py \\
        --key-file google_sa_key.json \\
        --primary  <ENCRYPTION_KEY_PRIMARY_VALUE> \\
        --fallback <ENCRYPTION_KEY_FALLBACK_VALUE>

After running:
  - secrets.enc will have a new "GOOGLE_SA_KEY_JSON" entry
  - Delete the local google_sa_key.json file — it is no longer needed
  - Commit the updated secrets.enc to the repo
  - DO NOT commit the raw .json key file (it is in .gitignore)
"""

import os
import sys
import json
import argparse
from pathlib import Path
from cryptography.fernet import Fernet

# ── path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets_manager import _get_keys


# ── encryption (mirror of add_flipboard_secrets.py) ──────────────────────────

def encrypt_value(value: str, primary: bytes, fallback: bytes) -> str:
    """Double-Fernet encrypt: Fernet(PRIMARY).encrypt(Fernet(FALLBACK).encrypt(plaintext))"""
    inner = Fernet(fallback).encrypt(value.encode("utf-8"))
    return Fernet(primary).encrypt(inner).decode("utf-8")


# ── vault helpers ─────────────────────────────────────────────────────────────

def load_vault(enc_file: Path) -> dict:
    if enc_file.exists():
        with open(enc_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_vault(enc_file: Path, vault: dict) -> None:
    with open(enc_file, "w", encoding="utf-8") as f:
        json.dump(vault, f, indent=2)


# ── main ──────────────────────────────────────────────────────────────────────

def add_google_sa_key(key_file: Path, dry_run: bool = False) -> None:
    # 1. Read and validate the JSON key file
    if not key_file.exists():
        sys.exit(
            f"ERROR: Key file not found: {key_file}\n"
            f"  Place the downloaded google_sa_key.json at:\n"
            f"    {ROOT / 'google_sa_key.json'}\n"
            f"  Then run this script again."
        )

    raw = key_file.read_text(encoding="utf-8")

    # Validate it parses as JSON and has required fields
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: Key file is not valid JSON: {e}")

    required_fields = ["type", "client_email", "private_key", "token_uri"]
    missing = [f for f in required_fields if f not in parsed]
    if missing:
        sys.exit(
            f"ERROR: Key file is missing required fields: {missing}\n"
            f"  Make sure you downloaded a Service Account JSON key (not an API key)."
        )

    if parsed.get("type") != "service_account":
        sys.exit(
            f"ERROR: Key file type is '{parsed.get('type')}' — expected 'service_account'.\n"
            f"  Download a Service Account JSON key from Google Cloud Console."
        )

    # Normalise: strip whitespace, store as compact JSON (no pretty-print)
    # This keeps the encrypted value small and avoids line-ending issues.
    compact = json.dumps(parsed, separators=(",", ":"))

    print(f"  Service account : {parsed['client_email']}")
    print(f"  Project         : {parsed.get('project_id', 'unknown')}")
    print(f"  Key ID          : {parsed.get('private_key_id', 'unknown')[:12]}…")
    print(f"  JSON size       : {len(compact):,} bytes")

    if dry_run:
        print("\n[DRY-RUN] Would encrypt and add GOOGLE_SA_KEY_JSON to secrets.enc.")
        print("[DRY-RUN] No files modified.")
        return

    # 2. Load encryption keys
    primary, fallback = _get_keys()

    # 3. Encrypt the compact JSON string
    print("\n  Encrypting with double-Fernet…")
    ciphertext = encrypt_value(compact, primary, fallback)

    # 4. Load existing vault, add/overwrite key, save
    enc_file = ROOT / "secrets.enc"
    vault = load_vault(enc_file)

    if "GOOGLE_SA_KEY_JSON" in vault:
        print("  [INFO] GOOGLE_SA_KEY_JSON already exists in secrets.enc — overwriting.")

    vault["GOOGLE_SA_KEY_JSON"] = ciphertext
    save_vault(enc_file, vault)

    print(f"  ✓ GOOGLE_SA_KEY_JSON written to {enc_file.name}")
    print(f"\n  Vault now contains {len(vault)} secret(s): {list(vault.keys())}")

    # 5. Safety reminder
    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ Done! Next steps:

  1. Delete the raw key file (no longer needed):
       del "{key_file}"

  2. Commit the updated secrets.enc:
       git add secrets.enc
       git commit -m "chore: add Google SA key to secrets vault"
       git push origin develop

  3. The GitHub workflow will auto-decrypt it using:
       ENCRYPTION_KEY_PRIMARY  (already a GitHub secret)
       ENCRYPTION_KEY_FALLBACK (already a GitHub secret)

  ⚠️  DO NOT commit the raw {key_file.name} file.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Add Google Service Account JSON key to secrets.enc vault",
    )
    ap.add_argument(
        "--key-file",
        default=str(ROOT / "google_sa_key.json"),
        help=(
            "Path to the Google SA .json key file "
            f"(default: {ROOT / 'google_sa_key.json'})"
        ),
    )
    ap.add_argument(
        "--primary",
        help="ENCRYPTION_KEY_PRIMARY value (optional if already in .env or environment)",
    )
    ap.add_argument(
        "--fallback",
        help="ENCRYPTION_KEY_FALLBACK value (optional if already in .env or environment)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the key file without writing anything",
    )
    args = ap.parse_args()

    # Inject keys into env if passed directly (avoids needing .env on this machine)
    if args.primary:
        os.environ["ENCRYPTION_KEY_PRIMARY"] = args.primary
    if args.fallback:
        os.environ["ENCRYPTION_KEY_FALLBACK"] = args.fallback

    print(f"\n{'='*52}")
    print(f"  Google SA Key → secrets.enc Injector")
    print(f"{'='*52}\n")

    add_google_sa_key(Path(args.key_file).resolve(), dry_run=args.dry_run)
