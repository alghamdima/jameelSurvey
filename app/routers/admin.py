import json
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
from app.core.security import verify_password
from app.core.tokens import create_admin_session_token
from app.core.auth import get_current_admin, require_admin, ensure_admin_user_exists
from app.db.session import get_db
from app.models import AdminUser, Survey, SurveyQuestion, SurveyResponse
from app.services.excel_exporter import generate_survey_excel

router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads"
STATIC_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = get_text
templates.env.globals["base_url"] = settings.BASE_URL

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
async def admin_login_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if admin:
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    lang = get_locale(request)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"lang": lang, "error": None}
    )

@router.post("/login", response_class=HTMLResponse)
async def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    ensure_admin_user_exists(db)
    user = db.query(AdminUser).filter(AdminUser.username == username.strip()).first()
    lang = get_locale(request)

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"lang": lang, "error": "auth_failed", "username": username}
        )

    response = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    token = create_admin_session_token(user.username)
    response.set_cookie(
        key="admin_session",
        value=token,
        max_age=60 * 60 * 24 * 7,  # 7 أيام
        httponly=True,
        samesite="lax"
    )
    return response

@router.get("/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_session")
    return response

# --- لوحة الإدارة الرئيسية واستعراض الاستبيانات ---

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
    lang = get_locale(request)
    surveys = db.query(Survey).order_by(Survey.created_at.desc()).all()
    
    # حساب عدد المشاركات لكل استبيان
    survey_stats = {}
    for s in surveys:
        resp_count = db.query(SurveyResponse).filter(SurveyResponse.survey_id == s.id).count()
        survey_stats[s.id] = resp_count

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
async def admin_new_survey(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
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
    survey_id = form_data.get("survey_id")
    title_ar = str(form_data.get("title_ar", "")).strip()
    title_en = str(form_data.get("title_en", "")).strip()
    desc_ar = str(form_data.get("description_ar", "")).strip()
    desc_en = str(form_data.get("description_en", "")).strip()
    theme_style = str(form_data.get("theme_style", "creative")).strip()
    header_image_url = str(form_data.get("header_image_url", "")).strip()
    background_url = str(form_data.get("background_url", "")).strip()
    questions_json_raw = form_data.get("questions_json", "[]")

    # التعامل مع رفع ملف صورة الغلاف أو الخلفية إن وجد
    header_file = form_data.get("header_image_file")
    if hasattr(header_file, "filename") and header_file.filename:
        ext = os.path.splitext(header_file.filename)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            filename = f"header_{secrets.token_hex(8)}{ext}"
            filepath = STATIC_UPLOADS_DIR / filename
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(header_file.file, buffer)
            header_image_url = f"/static/uploads/{filename}"

    bg_file = form_data.get("background_file")
    if hasattr(bg_file, "filename") and bg_file.filename:
        ext = os.path.splitext(bg_file.filename)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            filename = f"bg_{secrets.token_hex(8)}{ext}"
            filepath = STATIC_UPLOADS_DIR / filename
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(bg_file.file, buffer)
            background_url = f"/static/uploads/{filename}"

    try:
        questions_data = json.loads(str(questions_json_raw))
    except Exception:
        questions_data = []

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
            db.commit()
            return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
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

    # مسح الأسئلة القديمة وإعادة بناء الأسئلة والخيارات الجديدة
    db.query(SurveyQuestion).filter(SurveyQuestion.survey_id == survey.id).delete()

    for idx, q in enumerate(questions_data):
        q_key = q.get("key") or f"q_{idx+1}"
        q_type = q.get("question_type") or "single_choice"
        q_ar = str(q.get("text_ar", "")).strip()
        q_en = str(q.get("text_en", "")).strip()
        is_req = bool(q.get("is_required", True))
        opts = q.get("options") or []

        question = SurveyQuestion(
            survey_id=survey.id,
            question_key=q_key,
            text_ar=q_ar,
            text_en=q_en,
            question_type=q_type,
            is_required=is_req,
            order_index=idx,
            options_json=json.dumps(opts, ensure_ascii=False)
        )
        db.add(question)

    db.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/surveys/{survey_id}/edit", response_class=HTMLResponse)
async def admin_edit_survey(
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
            "error": None
        }
    )

# --- تغيير حالة الاستبيان (نشر / إغلاق / إرجاع لمسودة) ---

@router.post("/surveys/{survey_id}/status")
async def admin_change_survey_status(
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
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

# --- نسخ الاستبيان (Duplicate) ---

@router.post("/surveys/{survey_id}/duplicate")
async def admin_duplicate_survey(
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
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

# --- حذف الاستبيان (Delete) ---

@router.api_route("/surveys/{survey_id}/delete", methods=["GET", "POST"])
async def admin_delete_survey(
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
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

# --- استعراض نتائج الاستبيان ---

@router.get("/surveys/{survey_id}/results", response_class=HTMLResponse)
async def admin_survey_results(
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

    # تجميع الإحصائيات حسب معرفات الأسئلة والخيارات لضمان عدم انفصالها حسب لغة الموظف
    stats = {}
    total_answers_all_questions = 0

    for q in survey.questions:
        opts = q.get_options()
        opt_counts = {opt["key"]: 0 for opt in opts}
        text_answers = []
        question_answered_count = 0  # عدد المشاركين الذين أجابوا على هذا السؤال بالتحديد

        for r in responses:
            try:
                ans_map = json.loads(r.answers_json)
                q_ans = ans_map.get(q.question_key)
                if q_ans is not None:
                    if q.question_type == "single_choice" and q_ans in opt_counts:
                        opt_counts[q_ans] += 1
                        question_answered_count += 1
                    elif q.question_type == "multiple_choice" and isinstance(q_ans, list):
                        if len(q_ans) > 0:
                            question_answered_count += 1
                        for val in q_ans:
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
async def export_survey_results_excel(
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

    # حساب الإحصائيات الدقيقة
    stats = {}
    for q in survey.questions:
        opts = q.get_options()
        opt_counts = {opt["key"]: 0 for opt in opts}
        text_answers = []
        question_answered_count = 0

        for r in responses:
            try:
                ans_map = json.loads(r.answers_json) if r.answers_json else {}
                q_ans = ans_map.get(q.question_key)
                if q_ans is not None and q_ans != "":
                    if q.question_type == "single_choice" and q_ans in opt_counts:
                        opt_counts[q_ans] += 1
                        question_answered_count += 1
                    elif q.question_type == "multiple_choice" and isinstance(q_ans, list):
                        if len(q_ans) > 0:
                            question_answered_count += 1
                        for k in q_ans:
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
    safe_slug = "".join(c for c in (survey.title_en or survey.title_ar or "survey") if c.isalnum() or c in ("-", "_")).strip()
    filename = f"ALJUF_Survey_{survey.id}_{safe_slug}_{survey.public_id}.xlsx"

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
