import json
import base64
import hmac
import hashlib
import time
from typing import Optional
from app.core.config import settings

def create_participation_token(survey_public_id: str, employee_id: str) -> str:
    """
    إنشاء رمز سياق مشاركة مشفر وموقع رقمياً (HMAC-SHA256).
    لا يعتمد على كود قابل للتعديل بالمتصفح، ويحوي المعرف والرقم مع ختم زمني.
    """
    payload = {
        "sid": survey_public_id,
        "eid": employee_id,
        "ts": int(time.time())
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    payload_b64 = base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')
    
    signature = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        payload_b64.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return f"{payload_b64}.{signature}"

def verify_participation_token(token: str, expected_survey_public_id: str) -> Optional[str]:
    """
    التحقق من صحة الرمز واسترجاع الرقم الوظيفي.
    يرجع employee_id إذا كان الرمز صحيحاً ومطابقاً للاستبيان، وإلا يرجع None.
    """
    if not token or "." not in token:
        return None
    
    try:
        payload_b64, signature = token.split(".", 1)
        
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            payload_b64.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return None
        
        # إضافة الحشوة إذا لزم الأمر لفك الترميز
        rem = len(payload_b64) % 4
        padded = payload_b64 + ('=' * (4 - rem) if rem else '')
        raw_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(raw_bytes.decode('utf-8'))
        
        if payload.get("sid") != expected_survey_public_id:
            return None
        
        return payload.get("eid")
    except Exception:
        return None

def create_admin_session_token(username: str) -> str:
    """إنشاء رمز توثيق جلسة الأدمن."""
    payload = {
        "sub": username,
        "ts": int(time.time())
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    payload_b64 = base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')
    signature = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        payload_b64.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"

def verify_admin_session_token(token: str) -> Optional[str]:
    """التحقق من توكن جلسة الأدمن واستخراج اسم المستخدم."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            payload_b64.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        rem = len(payload_b64) % 4
        padded = payload_b64 + ('=' * (4 - rem) if rem else '')
        raw_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(raw_bytes.decode('utf-8'))
        return payload.get("sub")
    except Exception:
        return None
