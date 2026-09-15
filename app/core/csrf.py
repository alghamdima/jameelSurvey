import hmac
import secrets
from urllib.parse import urlsplit
from fastapi import Request, HTTPException
from app.core.config import settings
from app.core.tokens import sign_token, verify_token

def new_csrf_token() -> str:
    return sign_token("csrf", settings.ADMIN_SESSION_TTL_SECONDS, nonce=secrets.token_urlsafe(24))

async def require_csrf(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        allowed = urlsplit(settings.BASE_URL)
        if (parsed.scheme, parsed.netloc) != (allowed.scheme, allowed.netloc):
            raise HTTPException(403, "Invalid request origin")
    cookie = request.cookies.get("csrf_token", "")
    submitted = request.headers.get("x-csrf-token")
    if not submitted:
        form = await request.form()
        submitted = form.get("csrf_token", "")
    if (not isinstance(submitted, str) or not cookie
            or not hmac.compare_digest(cookie.encode(), submitted.encode()) or not verify_token(cookie, "csrf")):
        raise HTTPException(403, "Invalid or expired form. Reload the page and try again.")