"""Password hashing for email+password authentication.

stdlib hashlib.scrypt (memory-hard), no extra dependency. Stored format:
    scrypt$<salt-hex>$<hash-hex>
Verification is constant-time. Passwords live only here — never logged,
never returned by any endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_SALT_BYTES = 16
_KEY_BYTES = 32
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
# 128 * r * n ≈ 16 MiB — pass an explicit maxmem headroom so the params
# stay valid under different OpenSSL builds.
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
        maxmem=_MAXMEM,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # No password set (Google-only or manually created account).
        return False
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=len(expected),
        maxmem=_MAXMEM,
    )
    return hmac.compare_digest(digest, expected)
