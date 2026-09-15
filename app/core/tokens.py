import base64
import hashlib
import hmac
import json
import time
from typing import Optional
from app.core.config import settings

def sign_token(kind: str, ttl: int, **claims) -> str:
    now = int(time.time())
    payload = {"kind": kind, "iat": now, "exp": now + ttl, **claims}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"

def verify_token(token: str, kind: str) -> Optional[dict]:
    if not isinstance(token, str) or len(token) > 4096:
        return None
    try:
        raw, signature = token.split(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        now = int(time.time())
        if payload.get("kind") != kind or not isinstance(payload.get("exp"), int):
            return None
        if not isinstance(payload.get("iat"), int) or payload["iat"] > now + 30:
            return None
        if payload["exp"] <= now or payload["exp"] <= payload["iat"]:
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return None

def create_participation_token(survey_public_id: str, employee_id: str) -> str:
    return sign_token("participation", settings.PARTICIPATION_TTL_SECONDS, sid=survey_public_id, eid=employee_id)

def verify_participation_token(token: str, expected_survey_public_id: str) -> Optional[str]:
    payload = verify_token(token, "participation")
    if payload and payload.get("sid") == expected_survey_public_id and isinstance(payload.get("eid"), str):
        return payload["eid"]
    return None

def create_admin_session_token(username: str, session_id: str) -> str:
    return sign_token("admin", settings.ADMIN_SESSION_TTL_SECONDS, sub=username, jti=session_id)

def verify_admin_session_token(token: str) -> Optional[dict]:
    payload = verify_token(token, "admin")
    if payload and isinstance(payload.get("sub"), str) and isinstance(payload.get("jti"), str):
        return payload
    return None