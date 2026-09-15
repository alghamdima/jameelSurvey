import csv
from fastapi import HTTPException
from app.models import SurveyAudience
from app.services.employees import parse_employee_csv
from app.core.security import valid_employee_id
from app.core.i18n import get_text

MAX_CSV_BYTES = 2 * 1024 * 1024

def is_eligible_employee(db, survey, employee_id):
    if not valid_employee_id(employee_id):
        return False
    if survey.audience_mode == "all":
        return True
    if survey.audience_mode != "custom":
        return False
    return db.get(SurveyAudience, (survey.id, employee_id)) is not None

def prepare_audience(db, survey, form, lang):
    # Missing fields on older clients must never broaden an existing custom audience.
    mode = form.get("audience_mode", survey.audience_mode if survey else "all")
    if mode not in {"all", "custom"}:
        raise HTTPException(400, get_text("admin.audience_invalid_mode", lang))
    upload = form.get("audience_file")
    has_file = bool(getattr(upload, "filename", ""))
    if mode == "all":
        if has_file:
            raise HTTPException(400, get_text("admin.audience_select_custom", lang))
        return mode, None
    if not has_file:
        if survey and survey.audience_mode == "custom" and db.query(SurveyAudience).filter_by(survey_id=survey.id).first():
            return mode, None
        raise HTTPException(400, get_text("admin.audience_file_required", lang))
    if not upload.filename.lower().endswith(".csv"):
        raise HTTPException(400, get_text("admin.audience_invalid_file", lang))
    raw = upload.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(400, get_text("admin.audience_invalid_file", lang))
    try:
        ids, _, _ = parse_employee_csv(raw)
    except (ValueError, UnicodeError, csv.Error):
        raise HTTPException(400, get_text("admin.audience_invalid_file", lang))
    return mode, ids

def save_audience(db, survey, mode, ids):
    survey.audience_mode = mode
    if mode == "all" or ids is not None:
        db.query(SurveyAudience).filter_by(survey_id=survey.id).delete(synchronize_session=False)
        if mode == "custom":
            db.add_all([SurveyAudience(survey_id=survey.id, employee_id=eid) for eid in sorted(ids)])
