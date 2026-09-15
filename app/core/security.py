import hashlib
import hmac
import re
import secrets
import unicodedata

PASSWORD_ITERATIONS = 600_000

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        if hashed_password.startswith("pbkdf2_sha256$"):
            _, iterations, salt, digest = hashed_password.split("$")
            count = int(iterations)
            if not 100_000 <= count <= 2_000_000:
                return False
        else:
            # Accept existing hashes once; login upgrades them to randomly salted hashes.
            count, salt, digest = 100_000, "alj_secure_salt_surveys_2026", hashed_password
        expected = hashlib.pbkdf2_hmac("sha256", plain_password.encode(), salt.encode(), count).hex()
        return hmac.compare_digest(expected, digest)
    except (ValueError, TypeError):
        return False

def normalize_employee_id(raw_id: str) -> str:
    text = str(raw_id or "")
    text = "".join(c for c in text if not c.isspace() and unicodedata.category(c) != "Cf")
    digits = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
    return text.translate(str.maketrans(digits, "0123456789" * 2))

def valid_employee_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{1,50}", value))