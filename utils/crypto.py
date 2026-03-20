import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import secrets
import streamlit as st
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import base64

# ── KEY MANAGEMENT ────────────────────────────────────────────────────────
# The encryption key is derived from QAVI_ENCRYPT_KEY in Streamlit secrets.
# Set this in Streamlit Cloud: Settings → Secrets → add QAVI_ENCRYPT_KEY = "your-strong-passphrase"

def _get_fernet() -> Fernet:
    try:
        passphrase = st.secrets["QAVI_ENCRYPT_KEY"].encode()
    except Exception:
        # Fallback for local dev — set env var QAVI_ENCRYPT_KEY
        passphrase = os.environ.get("QAVI_ENCRYPT_KEY", "qavi-local-dev-key-change-in-prod").encode()

    # Derive a 32-byte key from passphrase using PBKDF2
    salt = b"qavi_salt_v1_static"  # static salt — key is constant per deployment
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase))
    return Fernet(key)

def encrypt(value: str) -> str:
    """Encrypt a string value. Returns empty string for empty input."""
    if not value:
        return ""
    try:
        f = _get_fernet()
        return f.encrypt(value.encode()).decode()
    except Exception:
        return value  # fallback: store unencrypted rather than crash

def decrypt(value: str) -> str:
    """Decrypt a Fernet-encrypted string. Returns empty string on failure."""
    if not value:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value  # already plain or corrupted

# ── PASSWORD HASHING ──────────────────────────────────────────────────────
# Passwords use SHA-256 with a random per-user salt stored alongside.
# Format stored: "sha256$<hex_salt>$<hex_hash>"

def hash_password(password: str) -> str:
    """Hash a password with a random salt. Returns storable string."""
    salt = secrets.token_hex(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 390000)
    return f"pbkdf2$sha256${salt}${h.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against stored hash."""
    if not password or not stored_hash:
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2":
            _, algo, salt, expected = parts
            h = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), 390000)
            return h.hex() == expected
        # Legacy SHA-256 fallback
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash
    except Exception:
        return False

def hash_advisor_key(key: str) -> str:
    """Hash the advisor key for storage comparison."""
    return hashlib.sha256(key.encode()).hexdigest()

def verify_advisor_key(key: str, stored_hash: str) -> bool:
    return hash_advisor_key(key) == stored_hash

# ── PASSWORD RESET ─────────────────────────────────────────────────────────

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)

# ── TITLE CASE HELPER ─────────────────────────────────────────────────────

def title_case(value: str) -> str:
    """Ensure first letter of each word is capitalised, rest lowercase."""
    if not value:
        return ""
    return " ".join(w.capitalize() for w in value.strip().split())

# ── INDIAN NUMBER FORMAT ──────────────────────────────────────────────────

def indian_format(amount: float) -> str:
    """Format number in Indian comma system: 1,00,000 not 100,000"""
    if amount < 0:
        return "−" + indian_format(-amount)
    amount = round(amount, 2)
    s = f"{amount:.2f}"
    integer_part, decimal_part = s.split(".")
    # Apply Indian comma system
    n = integer_part
    if len(n) <= 3:
        return f"{n}.{decimal_part}"
    last3 = n[-3:]
    rest = n[:-3]
    groups = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()
    formatted = ",".join(groups) + "," + last3
    return f"{formatted}.{decimal_part}"

def inr(amount: float, show_sign: bool = False) -> str:
    """Return formatted Indian rupee string."""
    sign = ""
    if show_sign:
        sign = "+" if amount >= 0 else "−"
        amount = abs(amount)
    return f"{sign}₹{indian_format(amount)}"

def fmt_date(date_str: str) -> str:
    """Convert any date string to DD-MM-YYYY format."""
    if not date_str:
        return "—"
    try:
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(date_str)[:10], fmt).strftime("%d-%m-%Y")
            except ValueError:
                continue
        return str(date_str)[:10]
    except Exception:
        return str(date_str)[:10]
