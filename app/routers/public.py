from starlette.concurrency import run_in_threadpool
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from fastapi import APIRouter, Depends, Request, Response, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.i18n import get_text
from app.core.security import normalize_employee_id, valid_employee_id
from app.services.audience import is_eligible_employee
from app.services.rate_limit import enforce_rate_limit
from app.schemas.survey import validate_answers
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
templates.env.globals["base_path"] = settings.base_path
templates.env.globals["url_for_app"] = settings.url_for_app

def get_locale(request: Request) -> str:
    cookie_lang = request.cookies.get("survey_lang")
    if cookie_lang in settings.SUPPORTED_LOCALES:
        return cookie_lang
    return settings.DEFAULT_LOCALE

# --- المسار الرئيسي للموقع / ---
@router.get("/", response_class=HTMLResponse)
def root_redirect(request: Request, db: Session = Depends(get_db)):
    """
    المسار الرئيسي:
    إذا كان الأدمن مسجلاً بالفعل، يُوجّه إلى لوحة الإدارة /admin/dashboard.
    إذا لم يكن مسجلاً، يُوجّه فوراً إلى صفحة تسجيل الدخول /admin/login.
    """
    admin = get_current_admin(request, db)
    if admin:
        return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=settings.url_for_app("/admin/login"), status_code=status.HTTP_303_SEE_OTHER)

# --- مسار تبديل اللغة العام ---
@router.get("/set-language")
def set_language(lang: str, redirect: str = "/"):
    target_lang = lang if lang in settings.SUPPORTED_LOCALES else settings.DEFAULT_LOCALE
    safe_redirect = redirect if (redirect.startswith("/") and not redirect.startswith("//")
        and "\\" not in redirect and not any(ord(c) < 32 for c in redirect)) else settings.url_for_app("/")
    response = RedirectResponse(url=safe_redirect, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="survey_lang",
        value=target_lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path=settings.base_path or "/"
    )
    return response

# --- فحص الصحة ---
@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    from sqlalchemy.exc import SQLAlchemyError
    try:
        # An empty survey table is healthy; employee files are optional.
        db.query(Survey.id).first()
        ready = True
        return JSONResponse({"status": "healthy" if ready else "not_ready"},
                            status_code=200 if ready else 503)
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse({"status": "not_ready"}, status_code=503)

# --- مسار الموظف: عرض الاستبيان /s/{public_id} ---
@router.get("/s/{public_id}", response_class=HTMLResponse)
def view_survey(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    lang = get_locale(request)
    survey = db.query(Survey).options(joinedload(Survey.questions)).filter(Survey.public_id == public_id).first()

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
            elif is_eligible_employee(db, survey, emp_id):
                verified_emp_id = emp_id

    if has_participated:
        return templates.TemplateResponse(request=request, name="survey/already_participated.html",
                                          context={"lang": lang, "survey": survey})
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
def verify_employee_number(
    public_id: str,
    request: Request,
    employee_id: str = Form(...),
    db: Session = Depends(get_db)
):
    enforce_rate_limit(db, request, "verify-employee", 60, 60)
    survey = db.query(Survey).filter(Survey.public_id == public_id).first()
    if not survey or survey.status != "published":
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "الاستبيان غير متاح للمشاركة حالياً."}
        )

    # معالجة وتوحيد الرقم الوظيفي
    clean_emp_id = normalize_employee_id(employee_id)
    if not valid_employee_id(clean_emp_id) or not is_eligible_employee(db, survey, clean_emp_id):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": get_text("survey.employee_not_allowed", get_locale(request))}
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
        max_age=settings.PARTICIPATION_TTL_SECONDS,  # 12 ساعة
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=settings.base_path or "/"
    )
    return response

# --- مسار إرسال إجابات الاستبيان ---
@router.post("/s/{public_id}/submit")
async def submit_survey_response(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    form_data = await request.form()
    return await run_in_threadpool(_submit_survey_form, public_id, request, db, form_data)


def _submit_survey_form(public_id, request, db, form_data):
    enforce_rate_limit(db, request, "submit-survey", 60, 60)
    db.execute(text("BEGIN IMMEDIATE"))
    survey = db.query(Survey).filter(Survey.public_id == public_id).first()
    if not survey or survey.status != "published":
        raise HTTPException(status_code=400, detail="الاستبيان غير متاح للإرسال.")

    token = form_data.get("participation_token") or request.cookies.get(f"part_{public_id}")

    if not token:
        raise HTTPException(status_code=401, detail="لم يتم توثيق الرقم الوظيفي بشكل صحيح.")

    # استخراج الرقم الوظيفي من التوكن الموقع في الخادم
    employee_id = verify_participation_token(str(token), public_id)
    if not employee_id or not is_eligible_employee(db, survey, employee_id):
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
    try:
        answers = validate_answers(survey.questions, form_data)
    except ValueError:
        message = ("يرجى إكمال الأسئلة المطلوبة والتحقق من الإجابات ثم المحاولة مجددًا."
                   if get_locale(request) == "ar" else
                   "Please complete required questions and check your answers before trying again.")
        return templates.TemplateResponse(
            request=request, name="survey/view.html", status_code=400,
            context={"lang": get_locale(request), "survey": survey, "questions": survey.questions,
                     "verified_emp_id": employee_id, "has_participated": False, "token": str(token),
                     "error": message, "base_url": settings.BASE_URL.rstrip("/")})

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
    resp.delete_cookie(f"part_{public_id}", path=settings.base_path or "/", secure=settings.cookie_secure)
    return resp
