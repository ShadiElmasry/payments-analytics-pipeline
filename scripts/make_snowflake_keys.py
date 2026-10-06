"""Create the RSA key pair Snowflake needs for passwordless (key-pair) login.

    python scripts/make_snowflake_keys.py

Writes the PRIVATE key to your home folder (~/.snowflake/), never inside the repo, and prints the PUBLIC key
text to paste into warehouse/snowflake_setup.sql. Never share or commit the private key.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

folder = Path.home() / ".snowflake"
private_path = folder / "payments_rsa_key.p8"
public_path = folder / "payments_rsa_key.pub"

if private_path.exists():
    raise SystemExit(f"{private_path} already exists. Delete it first if you really want a new key pair.")

folder.mkdir(parents=True, exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

private_path.write_bytes(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),       # the Spark connector needs an unencrypted PKCS8 key
))
public_pem = key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
public_path.write_text(public_pem)
try:
    os.chmod(private_path, 0o600)        # owner-only on Linux/macOS (ignored on Windows)
except OSError:
    pass

public_body = "".join(line for line in public_pem.splitlines() if not line.startswith("-----"))
print(f"Private key saved to: {private_path}")
print("Put that path in .env as SNOWFLAKE_PRIVATE_KEY_PATH.\n")
print("Paste this public key into warehouse/snowflake_setup.sql (RSA_PUBLIC_KEY):\n")
print(public_body)
