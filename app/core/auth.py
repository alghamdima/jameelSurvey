from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tokens import verify_admin_session_token
from app.db.session import get_db
from app.models import AdminUser
from app.core.security import hash_password

def get_current_admin(request: Request, db: Session = Depends(get_db)) -> Optional[AdminUser]:
    """
    استخراج الأدمن من الكوكي المشفر 'admin_session'.
    يقوم تلقائياً بتهيئة حساب الأدمن الافتراضي إذا لم يكن موجوداً في قاعدة البيانات.
    """
    # التأكد من وجود الأدمن الافتراضي
    ensure_admin_user_exists(db)
    
    token = request.cookies.get("admin_session")
    if not token:
        return None
    
    username = verify_admin_session_token(token)
    if not username:
        return None
    
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    return user

def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """إلزامية تسجيل الدخول كمسؤول للمسارات المحمية."""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": settings.url_for_app("/admin/login")}
        )
    _admin_initialized = True
    return admin

_admin_initialized = False

def ensure_admin_user_exists(db: Session) -> Optional[AdminUser]:
    global _admin_initialized
    if _admin_initialized:
        return None
    """التأكد من إنشاء مستخدم الأدمن من متغيرات البيئة إذا لم يكن موجوداً."""
    admin = db.query(AdminUser).filter(AdminUser.username == settings.ADMIN_USERNAME).first()
    if not admin:
        admin = AdminUser(
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD)
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    _admin_initialized = True
    return admin
