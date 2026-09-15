from datetime import datetime
from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.tokens import verify_admin_session_token
from app.db.session import get_db
from app.models import AdminUser, AdminSession
from app.core.security import hash_password, verify_password

def get_current_admin(request: Request, db: Session) -> Optional[AdminUser]:
    claims = verify_admin_session_token(request.cookies.get("admin_session", ""))
    if not claims:
        return None
    session = db.get(AdminSession, claims["jti"])
    if not session or session.expires_at <= datetime.utcnow():
        return None
    user = db.get(AdminUser, session.admin_id)
    return user if user and user.username == claims["sub"] else None

def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": settings.url_for_app("/admin/login")})
    return admin

def ensure_admin_user_exists(db: Session) -> AdminUser:
    admin = db.query(AdminUser).filter_by(username=settings.ADMIN_USERNAME).first()
    if admin:
        if not admin.password_hash.startswith("pbkdf2_sha256$") and any(
                verify_password(value, admin.password_hash)
                for value in ("admin123", "change_this_secure_password")):
            admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
            db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
            db.commit()
        return admin
    admin = AdminUser(username=settings.ADMIN_USERNAME, password_hash=hash_password(settings.ADMIN_PASSWORD))
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        admin = db.query(AdminUser).filter_by(username=settings.ADMIN_USERNAME).one()
    return admin