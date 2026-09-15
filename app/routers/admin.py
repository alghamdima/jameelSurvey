from starlette.concurrency import run_in_threadpool
import json
from datetime import datetime, timedelta
from sqlalchemy import text, func
from pydantic import ValidationError
import secrets
import string
import os
import shutil
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, Response, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.core.config import settings
from app.core.i18n import get_text
from app.core.security import verify_password, hash_password
from app.core.tokens import create_admin_session_token, verify_admin_session_token
from app.core.csrf import require_csrf
from app.schemas.survey import SurveyQuestions
from app.services.rate_limit import enforce_rate_limit
from app.core.auth import get_current_admin, require_admin, ensure_admin_user_exists
from app.db.session import get_db
from app.models import AdminUser, AdminSession, Survey, SurveyQuestion, SurveyResponse
from app.services.excel_exporter import generate_survey_excel
from app.services.image_optimizer import optimize_and_save_image
from app.services.audience import prepare_audience, save_audience
from app.models import SurveyAudience

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_csrf)])

def decoded_answers(responses):
    maps = []
    for response in responses:
        try:
            value = json.loads(response.answers_json)
            if isinstance(value, dict):
                maps.append(value)
        except (ValueError, TypeError):
            continue
    return maps


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads"
STATIC_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
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

def generate_public_id(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# --- تسجيل الدخول والخروج للأدمن ---

@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if admin:
        return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)
    
    lang = get_locale(request)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"lang": lang, "error": None}
    )

@router.post("/login", response_class=HTMLResponse)
def admin_login_submit(
    request: Request,
    username: str = Form(..., max_length=50),
    password: str = Form(..., max_length=1024),
    db: Session = Depends(get_db)
):
    enforce_rate_limit(db, request, "login", 20, 300)
    user = db.query(AdminUser).filter(AdminUser.username == username.strip()).first()
    lang = get_locale(request)

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"lang": lang, "error": "auth_failed", "username": username}
        )

    response = RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)
    if not user.password_hash.startswith("pbkdf2_sha256$"):
        user.password_hash = hash_password(password)
    session_id = secrets.token_urlsafe(32)
    db.query(AdminSession).filter(AdminSession.expires_at <= datetime.utcnow()).delete()
    db.add(AdminSession(id=session_id, admin_id=user.id,
                        expires_at=datetime.utcnow() + timedelta(seconds=settings.ADMIN_SESSION_TTL_SECONDS)))
    db.commit()
    token = create_admin_session_token(user.username, session_id)
    response.set_cookie(
        key="admin_session",
        value=token,
        max_age=settings.ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=settings.base_path or "/"
    )
    return response

@router.post("/logout")
def admin_logout(request: Request, db: Session = Depends(get_db)):
    claims = verify_admin_session_token(request.cookies.get("admin_session", ""))
    if claims:
        db.query(AdminSession).filter(AdminSession.id == claims["jti"]).delete()
        db.commit()
    response = RedirectResponse(url=settings.url_for_app("/admin/login"), status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_session", path=settings.base_path or "/", secure=settings.cookie_secure)
    return response

# --- لوحة الإدارة الرئيسية واستعراض الاستبيانات ---

@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
    lang = get_locale(request)
    surveys = db.query(Survey).order_by(Survey.created_at.desc()).all()
    
    # حساب عدد المشاركات لكل استبيان
    survey_stats = dict(db.query(SurveyResponse.survey_id, func.count(SurveyResponse.id)).group_by(SurveyResponse.survey_id).all())

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "lang": lang,
            "admin": admin,
            "surveys": surveys,
            "survey_stats": survey_stats,
            "base_url": settings.BASE_URL.rstrip('/')
        }
    )

# --- إنشاء وتعديل الاستبيانات ---

@router.get("/surveys/new", response_class=HTMLResponse)
def admin_new_survey(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
    lang = get_locale(request)
    return templates.TemplateResponse(
        request=request,
        name="admin/survey_form.html",
        context={"lang": lang, "admin": admin, "survey": None, "error": None}
    )

@router.post("/surveys/save")
async def admin_save_survey(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    form_data = await request.form()
    return await run_in_threadpool(_save_survey_form, request, db, admin, form_data)


def _save_survey_form(request, db, admin, form_data):
    survey_id = form_data.get("survey_id")
    title_ar = str(form_data.get("title_ar", "")).strip()
    title_en = str(form_data.get("title_en", "")).strip()
    desc_ar = str(form_data.get("description_ar", "")).strip()
    desc_en = str(form_data.get("description_en", "")).strip()
    theme_style = str(form_data.get("theme_style", "creative")).strip()
    header_image_url = str(form_data.get("header_image_url", "")).strip()
    background_url = str(form_data.get("background_url", "")).strip()
    questions_json_raw = form_data.get("questions_json", "[]")
    if not title_ar or not title_en or max(len(title_ar), len(title_en)) > 255:
        raise HTTPException(400, "Both survey titles are required (maximum 255 characters)")
    if max(len(desc_ar), len(desc_en)) > 10000 or theme_style not in {"creative", "classic"}:
        raise HTTPException(400, "Invalid description or theme")
    for image_url in (header_image_url, background_url):
        if len(image_url) > 500 or (image_url and not image_url.startswith(("/", "https://", "http://"))):
            raise HTTPException(400, "Invalid image URL")
    if survey_id and (not isinstance(survey_id, str) or not survey_id.isascii() or not survey_id.isdecimal()):
        raise HTTPException(400, "Invalid survey ID")
    try:
        questions_data = SurveyQuestions(questions=json.loads(str(questions_json_raw))).model_dump()["questions"]
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(400, "Invalid questions: check types, translations, options and unique identifiers")
    # Serialize edits with submissions so an in-flight response cannot refer to deleted questions.
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    existing_survey = db.get(Survey, int(survey_id)) if survey_id else None
    if survey_id and existing_survey is None:
        raise HTTPException(404, "Survey not found")
    try:
        audience_mode, audience_ids = prepare_audience(db, existing_survey, form_data, get_locale(request))
    except HTTPException as exc:
        # Keep the edited values and questions on the page; browsers require re-selecting file inputs.
        from types import SimpleNamespace
        draft = SimpleNamespace(
            id=int(survey_id) if survey_id else "",
            title_ar=title_ar, title_en=title_en, description_ar=desc_ar, description_en=desc_en,
            theme_style=theme_style, header_image_url=header_image_url, background_url=background_url,
            audience_mode=form_data.get("audience_mode", "custom"),
            questions=[SurveyQuestion(question_key=q["key"], text_ar=q["text_ar"], text_en=q["text_en"],
                question_type=q["question_type"], is_required=q["is_required"],
                options_json=json.dumps(q["options"], ensure_ascii=False)) for q in questions_data])
        response_count = db.query(SurveyResponse).filter_by(survey_id=int(survey_id)).count() if survey_id else 0
        audience_count = db.query(SurveyAudience).filter_by(survey_id=int(survey_id)).count() if survey_id else 0
        db.rollback()
        return templates.TemplateResponse(request=request, name="admin/survey_form.html", status_code=exc.status_code,
            context={"lang":get_locale(request), "admin":admin, "survey":draft, "error":exc.detail,
                     "response_count":response_count, "audience_count":audience_count})


    # التعامل مع رفع ملف صورة الغلاف أو الخلفية بضغط فائق السرعة وتنسيق WebP
    header_file = form_data.get("header_image_file")
    if hasattr(header_file, "filename") and header_file.filename:
        ext = os.path.splitext(header_file.filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            raise HTTPException(400, "Unsupported image format")
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            try:
                filename = optimize_and_save_image(header_file.file, STATIC_UPLOADS_DIR, prefix="header", max_dimension=1400)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            header_image_url = settings.url_for_app(f"/static/uploads/{filename}")

    bg_file = form_data.get("background_file")
    if hasattr(bg_file, "filename") and bg_file.filename:
        ext = os.path.splitext(bg_file.filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            raise HTTPException(400, "Unsupported image format")
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            try:
                filename = optimize_and_save_image(bg_file.file, STATIC_UPLOADS_DIR, prefix="bg", max_dimension=1920)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            background_url = settings.url_for_app(f"/static/uploads/{filename}")


    if not title_ar or not title_en:
        raise HTTPException(status_code=400, detail="العنوان باللغتين مطلوب.")

    if survey_id:
        survey = db.query(Survey).filter(Survey.id == int(survey_id)).first()
        if not survey:
            raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")
        
        survey.title_ar = title_ar
        survey.title_en = title_en
        survey.description_ar = desc_ar
        survey.description_en = desc_en
        survey.theme_style = theme_style
        # تحديث الصورة والخلفية حتى لو تم إفراغها (إزالة الصورة)
        survey.header_image_url = header_image_url or None
        survey.background_url = background_url or None

        # إذا كان هناك مشاركات مسجلة، امنع تعديل بنية الأسئلة
        resp_count = db.query(SurveyResponse).filter(SurveyResponse.survey_id == survey.id).count()
        if resp_count > 0:
            save_audience(db, survey, audience_mode, audience_ids)
            db.commit()
            return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)
    else:
        # إنشاء استبيان جديد مع public_id فريد
        public_id = generate_public_id()
        while db.query(Survey).filter(Survey.public_id == public_id).first():
            public_id = generate_public_id()

        survey = Survey(
            public_id=public_id,
            title_ar=title_ar,
            title_en=title_en,
            description_ar=desc_ar,
            description_en=desc_en,
            theme_style=theme_style,
            header_image_url=header_image_url or None,
            background_url=background_url or None,
            status="draft"
        )
        db.add(survey)
        db.flush()

    save_audience(db, survey, audience_mode, audience_ids)

    # مسح الأسئلة القديمة وإعادة بناء الأسئلة والخيارات الجديدة
    db.query(SurveyQuestion).filter(SurveyQuestion.survey_id == survey.id).delete()

    new_questions = [
        SurveyQuestion(
            survey_id=survey.id,
            question_key=q.get("key") or f"q_{idx+1}",
            text_ar=str(q.get("text_ar", "")).strip(),
            text_en=str(q.get("text_en", "")).strip(),
            question_type=q.get("question_type") or "single_choice",
            is_required=bool(q.get("is_required", True)),
            order_index=idx,
            options_json=json.dumps(q.get("options") or [], ensure_ascii=False)
        )
        for idx, q in enumerate(questions_data)
    ]
    if new_questions:
        db.add_all(new_questions)

    db.commit()
    return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)

@router.get("/surveys/{survey_id}/edit", response_class=HTMLResponse)
def admin_edit_survey(
    survey_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    lang = get_locale(request)
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")
    
    resp_count = db.query(SurveyResponse).filter(SurveyResponse.survey_id == survey.id).count()

    return templates.TemplateResponse(
        request=request,
        name="admin/survey_form.html",
        context={
            "lang": lang,
            "admin": admin,
            "survey": survey,
            "response_count": resp_count,
            "audience_count": db.query(SurveyAudience).filter_by(survey_id=survey.id).count(),
            "error": None
        }
    )

# --- تغيير حالة الاستبيان (نشر / إغلاق / إرجاع لمسودة) ---

@router.post("/surveys/{survey_id}/status")
def admin_change_survey_status(
    survey_id: int,
    status_val: str = Form(...),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")

    if status_val not in ["draft", "published", "closed"]:
        raise HTTPException(status_code=400, detail="حالة غير صالحة.")

    # التحقق من اكتمال الترجمات قبل النشر
    if status_val == "published":
        missing = []
        if not survey.title_ar.strip():
            missing.append("عنوان الاستبيان بالعربية")
        if not survey.title_en.strip():
            missing.append("Survey title in English")

        if not survey.questions:
            missing.append("الاستبيان لا يحتوي على أي أسئلة")

        for q in survey.questions:
            if not q.text_ar.strip():
                missing.append(f"نص السؤال ({q.question_key}) بالعربية")
            if not q.text_en.strip():
                missing.append(f"Question text ({q.question_key}) in English")
            if q.question_type in ["single_choice", "multiple_choice"]:
                opts = q.get_options()
                if not opts:
                    missing.append(f"خيارات السؤال ({q.question_key})")
                for opt in opts:
                    if not opt.get("text_ar", "").strip() or not opt.get("text_en", "").strip():
                        missing.append(f"ترجمة أحد خيارات السؤال ({q.question_key})")

        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"لا يمكن نشر الاستبيان لوجود حقول ناقصة الترجمة: {', '.join(missing)}"
            )

    survey.status = status_val
    db.commit()
    return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)

# --- نسخ الاستبيان (Duplicate) ---

@router.post("/surveys/{survey_id}/duplicate")
def admin_duplicate_survey(
    survey_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")

    new_pub_id = generate_public_id()
    while db.query(Survey).filter(Survey.public_id == new_pub_id).first():
        new_pub_id = generate_public_id()

    new_survey = Survey(
        public_id=new_pub_id,
        title_ar=f"{survey.title_ar} (نسخة)",
        title_en=f"{survey.title_en} (Copy)",
        description_ar=survey.description_ar,
        description_en=survey.description_en,
        theme_style=survey.theme_style,
        header_image_url=survey.header_image_url,
        background_url=survey.background_url,
        status="draft"
    )
    db.add(new_survey)
    db.flush()
    new_survey.audience_mode = survey.audience_mode
    db.add_all([SurveyAudience(survey_id=new_survey.id, employee_id=entry.employee_id)
                for entry in survey.audience])

    for q in survey.questions:
        new_q = SurveyQuestion(
            survey_id=new_survey.id,
            question_key=q.question_key,
            text_ar=q.text_ar,
            text_en=q.text_en,
            question_type=q.question_type,
            is_required=q.is_required,
            order_index=q.order_index,
            options_json=q.options_json
        )
        db.add(new_q)

    db.commit()
    return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)

# --- حذف الاستبيان (Delete) ---

@router.post("/surveys/{survey_id}/delete")
def admin_delete_survey(
    survey_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    """حذف الاستبيان نهائياً مع كافة أسئلته وإجابات الموظفين المسجلة."""
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")

    db.delete(survey)
    db.commit()
    return RedirectResponse(url=settings.url_for_app("/admin/dashboard"), status_code=status.HTTP_303_SEE_OTHER)

# --- استعراض نتائج الاستبيان ---

@router.get("/surveys/{survey_id}/results", response_class=HTMLResponse)
def admin_survey_results(
    survey_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    lang = get_locale(request)
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")

    responses = db.query(SurveyResponse).filter(SurveyResponse.survey_id == survey.id).all()
    total_responses = len(responses)
    answer_maps = decoded_answers(responses)

    # تجميع الإحصائيات حسب معرفات الأسئلة والخيارات لضمان عدم انفصالها حسب لغة الموظف
    stats = {}
    total_answers_all_questions = 0

    for q in survey.questions:
        opts = q.get_options()
        opt_counts = {opt["key"]: 0 for opt in opts}
        text_answers = []
        question_answered_count = 0  # عدد المشاركين الذين أجابوا على هذا السؤال بالتحديد

        for ans_map in answer_maps:
            try:
                q_ans = ans_map.get(q.question_key)
                if q_ans is not None:
                    if q.question_type == "single_choice" and q_ans in opt_counts:
                        opt_counts[q_ans] += 1
                        question_answered_count += 1
                    elif q.question_type == "multiple_choice" and isinstance(q_ans, list):
                        if len(q_ans) > 0:
                            question_answered_count += 1
                        for val in set(q_ans):
                            if val in opt_counts:
                                opt_counts[val] += 1
                    elif q.question_type == "text" and str(q_ans).strip():
                        text_answers.append(str(q_ans).strip())
                        question_answered_count += 1
            except Exception:
                continue

        # حساب مجموع الاختيارات لهذا السؤال (مفيد لتحديد الأكثر اختياراً وكسور النسبة)
        total_selections = sum(opt_counts.values()) if q.question_type in ["single_choice", "multiple_choice"] else len(text_answers)
        total_answers_all_questions += question_answered_count

        # تحديد الخيار الأكثر تكراراً / فائزاً
        top_opt_key = None
        if opt_counts:
            max_c = max(opt_counts.values())
            if max_c > 0:
                top_opts = [k for k, v in opt_counts.items() if v == max_c]
                top_opt_key = top_opts[0] if len(top_opts) == 1 else None

        # نسبة إجابة هذا السؤال من إجمالي المشاركين في الاستبيان
        response_rate = round((question_answered_count / total_responses * 100), 1) if total_responses > 0 else 0

        stats[q.question_key] = {
            "question": q,
            "opt_counts": opt_counts,
            "text_answers": text_answers,
            "answered_count": question_answered_count,
            "response_rate": response_rate,
            "total_selections": total_selections,
            "top_opt_key": top_opt_key
        }

    # معدل الإكمال العام للاستبيان
    total_possible_answers = total_responses * len(survey.questions) if survey.questions else 0
    overall_completion_rate = round((total_answers_all_questions / total_possible_answers * 100), 1) if total_possible_answers > 0 else 0

    return templates.TemplateResponse(
        request=request,
        name="admin/results.html",
        context={
            "lang": lang,
            "admin": admin,
            "survey": survey,
            "total_responses": total_responses,
            "overall_completion_rate": overall_completion_rate,
            "stats": stats,
            "base_url": settings.BASE_URL.rstrip('/')
        }
    )


@router.get("/surveys/{survey_id}/export/excel")
def export_survey_results_excel(
    survey_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin)
):
    """تصدير تقرير إحصائي وتحليلي وسجل إجابات الاستبيان كملف Excel (.xlsx) بهوية عبد اللطيف جميل."""
    lang = get_locale(request)
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="الاستبيان غير موجود.")

    responses = db.query(SurveyResponse).filter(SurveyResponse.survey_id == survey.id).order_by(SurveyResponse.submitted_at.desc()).all()
    total_responses = len(responses)
    answer_maps = decoded_answers(responses)

    # حساب الإحصائيات الدقيقة
    stats = {}
    for q in survey.questions:
        opts = q.get_options()
        opt_counts = {opt["key"]: 0 for opt in opts}
        text_answers = []
        question_answered_count = 0

        for ans_map in answer_maps:
            try:
                q_ans = ans_map.get(q.question_key)
                if q_ans is not None and q_ans != "":
                    if q.question_type == "single_choice" and q_ans in opt_counts:
                        opt_counts[q_ans] += 1
                        question_answered_count += 1
                    elif q.question_type == "multiple_choice" and isinstance(q_ans, list):
                        if len(q_ans) > 0:
                            question_answered_count += 1
                        for k in set(q_ans):
                            if k in opt_counts:
                                opt_counts[k] += 1
                    elif q.question_type == "text" and str(q_ans).strip():
                        text_answers.append(str(q_ans).strip())
                        question_answered_count += 1
            except Exception:
                continue

        top_opt_key = None
        if opt_counts:
            max_c = max(opt_counts.values())
            if max_c > 0:
                top_opts = [k for k, v in opt_counts.items() if v == max_c]
                top_opt_key = top_opts[0] if len(top_opts) == 1 else None

        response_rate = round((question_answered_count / total_responses * 100), 1) if total_responses > 0 else 0
        stats[q.question_key] = {
            "question": q,
            "opt_counts": opt_counts,
            "text_answers": text_answers,
            "answered_count": question_answered_count,
            "response_rate": response_rate,
            "total_selections": sum(opt_counts.values()) if q.question_type in ["single_choice", "multiple_choice"] else len(text_answers),
            "top_opt_key": top_opt_key
        }

    excel_stream = generate_survey_excel(survey, responses, stats, lang=lang)
    safe_slug = "".join(c for c in (survey.title_en or survey.title_ar or "survey") if (c.isascii() and c.isalnum()) or c in ("-", "_")).strip()[:80] or "survey"
    filename = f"ALJUF_Survey_{survey.id}_{safe_slug}_{survey.public_id}.xlsx"

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/surveys/audience-template")
def audience_csv_template(admin: AdminUser = Depends(require_admin)):
    return Response(content="\ufeffEmployee No.\r\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="survey_employees_template.csv"'})
