import re
import hashlib
import hmac
import unicodedata

def hash_password(password: str) -> str:
    """
    تشفير كلمة المرور باستخدام PBKDF2-HMAC-SHA256 من المكتبة القياسية لبايثون
    لضمان التوافق والأمان العالي دون أي مشاكل مع إصدارات bcrypt/passlib.
    """
    salt = "alj_secure_salt_surveys_2026"
    pwd_bytes = password.encode('utf-8')
    key = hashlib.pbkdf2_hmac('sha256', pwd_bytes, salt.encode('utf-8'), 100000)
    return key.hex()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    expected = hash_password(plain_password)
    return hmac.compare_digest(expected, hashed_password)

def normalize_employee_id(raw_id: str) -> str:
    """
    توحيد الرقم الوظيفي:
    - التعامل معه كنص للحفاظ على الأصفار في بدايته.
    - إزالة المسافات الطرفية والداخلية الزائدة.
    - تحويل الأرقام العربية والمشرقية (٠-٩) إلى أرقام قياسية (0-9).
    - تنظيف أي حروف تحكم غير مرئية.
    """
    if not raw_id:
        return ""
    
    # تنظيف المسافات والرموز غير المرئية
    text = str(raw_id).strip()
    
    # جدول تحويل الأرقام العربية الشرقية والفارسية
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    ascii_digits = "0123456789"
    
    tr_table = str.maketrans(arabic_digits + persian_digits, ascii_digits * 2)
    normalized = text.translate(tr_table)
    
    # إزالة أي مسافات زائدة
    normalized = re.sub(r"\s+", "", normalized)
    return normalized
