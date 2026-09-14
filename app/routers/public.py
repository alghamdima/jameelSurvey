from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from fastapi import APIRouter, Depends, Request, Response, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.i18n import get_text
from app.core.security import normalize_employee_id
from app.core.tokens import create_participation_token, verify_participation_token
from app.core.auth import get_current_admin
from app.db.session import get_db
from app.models import Survey, SurveyQuestion, SurveyResponse

router = APIRouter(tags=["surveys"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

templates.env.globals["t"] = get_text
templates.env.globals["current_year"] = datetime.now().year
templates.env.globals["base_url"] = settings.BASE_URL

def get_locale(request: Request) -> str:
    cookie_lang = request.cookies.get("survey_lang")
    if cookie_lang in settings.SUPPORTED_LOCALES:
        return cookie_lang
    return settings.DEFAULT_LOCALE

# --- المسار الرئيسي للموقع / ---
@router.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request, db: Session = Depends(get_db)):
    """
    المسار الرئيسي:
    إذا كان الأدمن مسجلاً بالفعل، يُوجّه إلى لوحة الإدارة /admin/dashboard.
    إذا لم يكن مسجلاً، يُوجّه فوراً إلى صفحة تسجيل الدخول /admin/login.
    """
    admin = get_current_admin(request, db)
    if admin:
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

# --- مسار تبديل اللغة العام ---
@router.get("/set-language")
async def set_language(lang: str, redirect: str = "/"):
    target_lang = lang if lang in settings.SUPPORTED_LOCALES else settings.DEFAULT_LOCALE
    safe_redirect = redirect if redirect.startswith("/") else "/"
    response = RedirectResponse(url=safe_redirect, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="survey_lang",
        value=target_lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax"
    )
    return response

# --- فحص الصحة ---
@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV
    }

# --- مسار الموظف: عرض الاستبيان /s/{public_id} ---
@router.get("/s/{public_id}", response_class=HTMLResponse)
async def view_survey(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    lang = get_locale(request)
    survey = db.query(Survey).filter(Survey.public_id == public_id).first()

    # إذا كان الاستبيان غير موجود أو في حالة مسودة، لا يعرض للعامة
    if not survey or survey.status == "draft":
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={
                "lang": lang,
                "message": "الاستبيان المطلوب غير موجود أو غير منشور حالياً." if lang == "ar" else "The requested survey does not exist or is not published yet."
            },
            status_code=status.HTTP_404_NOT_FOUND
        )

    # إذا كان الاستبيان مغلقاً، اعرض صفحة الإغلاق مباشرة دون طلب الرقم الوظيفي
    if survey.status == "closed":
        return templates.TemplateResponse(
            request=request,
            name="survey/closed.html",
            context={"lang": lang, "survey": survey}
        )

    # فحص إذا كان هناك سياق مشاركة موثق بالـ Cookie خاص بهذا الاستبيان
    cookie_token = request.cookies.get(f"part_{public_id}")
    verified_emp_id = None
    has_participated = False

    if cookie_token:
        emp_id = verify_participation_token(cookie_token, public_id)
        if emp_id:
            # التحقق مما إذا كان قد شارك بالفعل في قاعدة البيانات
            existing = db.query(SurveyResponse).filter(
                SurveyResponse.survey_id == survey.id,
                SurveyResponse.employee_id == emp_id
            ).first()
            if existing:
                has_participated = True
            else:
                verified_emp_id = emp_id

    return templates.TemplateResponse(
        request=request,
        name="survey/view.html",
        context={
            "lang": lang,
            "survey": survey,
            "questions": survey.questions,
            "verified_emp_id": verified_emp_id,
            "has_participated": has_participated,
            "token": cookie_token or "",
            "base_url": settings.BASE_URL.rstrip('/')
        }
    )

# --- مسار التحقق من الرقم الوظيفي عبر الـ Modal ---
@router.post("/s/{public_id}/verify-employee")
async def verify_employee_number(
    public_id: str,
    request: Request,
    employee_id: str = Form(...),
    db: Session = Depends(get_db)
):
    survey = db.query(Survey).filter(Survey.public_id == public_id).first()
    if not survey or survey.status != "published":
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "الاستبيان غير متاح للمشاركة حالياً."}
        )

    # معالجة وتوحيد الرقم الوظيفي
    clean_emp_id = normalize_employee_id(employee_id)
    if not clean_emp_id or len(clean_emp_id) < 2:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "يرجى إدخال رقم وظيفي صحيح."}
        )

    # التحقق من وجود مشاركة سابقة
    existing = db.query(SurveyResponse).filter(
        SurveyResponse.survey_id == survey.id,
        SurveyResponse.employee_id == clean_emp_id
    ).first()

    if existing:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "already_participated",
                "message_ar": "سبق أن شاركت في هذا الاستبيان.",
                "message_en": "You have already participated in this survey."
            }
        )

    # إنشاء رمز سياق مشاركة مشفر وموقع يربط بين الاستبيان والرقم الوظيفي
    token = create_participation_token(public_id, clean_emp_id)

    response = JSONResponse(
        content={
            "success": True,
            "employee_id": clean_emp_id,
            "token": token
        }
    )
    # حفظه في الكوكي لضمان استمراره أثناء تعبئة الاستبيان حتى لو تبدلت اللغة
    response.set_cookie(
        key=f"part_{public_id}",
        value=token,
        max_age=60 * 60 * 12,  # 12 ساعة
        httponly=True,
        samesite="lax"
    )
    return response

# --- مسار إرسال إجابات الاستبيان ---
@router.post("/s/{public_id}/submit")
async def submit_survey_response(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    survey = db.query(Survey).filter(Survey.public_id == public_id).first()
    if not survey or survey.status != "published":
        raise HTTPException(status_code=400, detail="الاستبيان غير متاح للإرسال.")

    form_data = await request.form()
    token = form_data.get("participation_token") or request.cookies.get(f"part_{public_id}")

    if not token:
        raise HTTPException(status_code=401, detail="لم يتم توثيق الرقم الوظيفي بشكل صحيح.")

    # استخراج الرقم الوظيفي من التوكن الموقع في الخادم
    employee_id = verify_participation_token(str(token), public_id)
    if not employee_id:
        raise HTTPException(status_code=401, detail="سياق المشاركة غير صالح أو منتهي الصلاحية.")

    # إعادة التحقق من عدم وجود مشاركة سابقة قبل الحفظ
    existing = db.query(SurveyResponse).filter(
        SurveyResponse.survey_id == survey.id,
        SurveyResponse.employee_id == employee_id
    ).first()

    if existing:
        return templates.TemplateResponse(
            request=request,
            name="survey/already_participated.html",
            context={"lang": get_locale(request), "survey": survey}
        )

    # جمع الإجابات
    answers = {}
    for q in survey.questions:
        q_key = q.question_key
        if q.question_type == "multiple_choice":
            vals = form_data.getlist(q_key)
            if q.is_required and not vals:
                raise HTTPException(status_code=400, detail=f"الإجابة على السؤال {q_key} مطلوبة.")
            answers[q_key] = vals
        else:
            val = form_data.get(q_key, "")
            if isinstance(val, str):
                val = val.strip()
            if q.is_required and not val:
                raise HTTPException(status_code=400, detail=f"الإجابة على السؤال {q_key} مطلوبة.")
            answers[q_key] = val

    # حفظ المشاركة داخل Transaction مع حماية الـ UNIQUE Constraint المتزامنة
    try:
        new_response = SurveyResponse(
            survey_id=survey.id,
            employee_id=employee_id,
            answers_json=json.dumps(answers, ensure_ascii=False)
        )
        db.add(new_response)
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="survey/already_participated.html",
            context={"lang": get_locale(request), "survey": survey}
        )

    # عرض صفحة الشكر وحذف كوكي سياق المشاركة المؤقت
    lang = get_locale(request)
    resp = templates.TemplateResponse(
        request=request,
        name="survey/thank_you.html",
        context={"lang": lang, "survey": survey}
    )
    resp.delete_cookie(f"part_{public_id}")
    return resp
