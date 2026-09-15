import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Keep all test state and employees isolated from the real roster.
TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEST_ROOT.name) / "test.db").replace("\\", "/")
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production-12345"
os.environ["ADMIN_PASSWORD"] = "test-only-admin-password-12345"
os.environ["BASE_URL"] = "http://testserver"
os.environ["EMPLOYEE_CSV_PATH"] = ""
os.environ["SURVEY_DEBUG"] = "false"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete
from app.main import app
from app.db.session import SessionLocal, engine
from app.models import Survey, SurveyQuestion, SurveyResponse, Employee, AdminSession, RateLimitBucket
from app.core.config import settings
from app.core.security import hash_password, verify_password, normalize_employee_id
from app.core.tokens import create_participation_token, verify_participation_token, sign_token
from app.services.employees import import_employee_csv
from app.services.image_optimizer import optimize_and_save_image
from app.services.excel_exporter import generate_survey_excel
from openpyxl import load_workbook

@pytest.fixture(scope="session", autouse=True)
def migrate():
    command.upgrade(Config("alembic.ini"), "head")
    yield
    engine.dispose()
    TEST_ROOT.cleanup()

@pytest.fixture
def client():
    with SessionLocal() as db:
        for model in (AdminSession, RateLimitBucket, SurveyResponse, SurveyQuestion, Survey, Employee):
            db.execute(delete(model))
        db.add_all([Employee(employee_id="00123", active=True), Employee(employee_id="456", active=False)])
        db.commit()
    with TestClient(app) as client:
        yield client

@pytest.fixture
def survey(client):
    with SessionLocal() as db:
        s = Survey(public_id="test123", title_ar="اختبار", title_en="Test", status="published")
        db.add(s)
        db.flush()
        db.add_all([
            SurveyQuestion(survey_id=s.id, question_key="q_1", text_ar="واحد", text_en="One",
                question_type="multiple_choice", is_required=True, order_index=0,
                options_json=json.dumps([{"key":"opt_1","text_ar":"نعم","text_en":"Yes"},
                                         {"key":"opt_2","text_ar":"لا","text_en":"No"}])),
            SurveyQuestion(survey_id=s.id, question_key="q_2", text_ar="تعليق", text_en="Comment",
                question_type="text", is_required=False, order_index=1, options_json="[]")
        ])
        db.commit()
        return s.id

def login(client):
    response = client.get("/admin/login")
    assert response.status_code == 200
    csrf = client.cookies.get("csrf_token")
    response = client.post("/admin/login", data={
        "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD, "csrf_token": csrf
    }, follow_redirects=False)
    assert response.status_code == 303, response.text
    return csrf

def test_password_hashes_and_legacy_upgrade():
    assert hash_password("secret") != hash_password("secret")
    assert verify_password("secret", hash_password("secret"))
    legacy = hashlib.pbkdf2_hmac("sha256", b"secret", b"alj_secure_salt_surveys_2026", 100000).hex()
    assert verify_password("secret", legacy)
    assert not verify_password("wrong", legacy)

def test_normalization_preserves_zeros():
    assert normalize_employee_id(" \u200e٠٠١۲۳ ") == "00123"

def test_token_expiry_and_purpose():
    assert verify_participation_token(sign_token("participation", -1, sid="x", eid="00123"), "x") is None
    token = create_participation_token("x", "00123")
    assert verify_participation_token(token, "x") == "00123"
    assert verify_participation_token(token, "y") is None
    assert verify_participation_token(sign_token("admin", 60, sid="x", eid="00123"), "x") is None

def test_import_atomic_and_preserves_zeros(client, tmp_path):
    path = tmp_path / "employees.csv"
    path.write_text("Employee No.\n00123\n٠٠١٢٣\n00999\n", encoding="utf-8-sig")
    with SessionLocal() as db:
        result = import_employee_csv(db, path)
        assert result == {"active_employees": 2, "duplicates_ignored": 1}
        assert db.get(Employee, "00123").active
        path.write_text("Employee No.\n111\n1.2e4\n", encoding="utf-8")
        with pytest.raises(ValueError):
            import_employee_csv(db, path)
        assert db.get(Employee, "00123").active
        assert db.get(Employee, "111") is None

@pytest.mark.parametrize("employee", ["abc", "=1+1"])
def test_invalid_employee_format_rejected(client, survey, employee):
    assert client.post("/s/test123/verify-employee", data={"employee_id": employee}).status_code == 400

def test_central_roster_does_not_restrict_open_survey(client, survey):
    response = client.post("/s/test123/verify-employee", data={"employee_id": "٠٠١٢٣"})
    assert response.status_code == 200
    token = response.json()["token"]
    with SessionLocal() as db:
        db.get(Employee, "00123").active = False
        db.commit()
    assert client.post("/s/test123/submit", data={"participation_token": token, "q_1": "opt_1"}).status_code == 200

@pytest.mark.parametrize("values", [["unknown"], ["opt_1","opt_1"], []])
def test_bad_answers_rejected_without_losing_form(client, survey, values):
    token = create_participation_token("test123", "00123")
    result = client.post("/s/test123/submit", data={"participation_token": token, "q_1": values})
    assert result.status_code == 400, result.text
    assert 'survey-submit-form' in result.text
    with SessionLocal() as db:
        assert db.query(SurveyResponse).count() == 0

def test_submit_once_and_export_formula_as_text(client, survey):
    token = create_participation_token("test123", "00123")
    data = {"participation_token": token, "q_1": ["opt_1","opt_2"], "q_2": "=1+1"}
    assert client.post("/s/test123/submit", data=data).status_code == 200
    assert client.post("/s/test123/submit", data=data).status_code == 200
    with SessionLocal() as db:
        assert db.query(SurveyResponse).count() == 1
        s = db.get(Survey, survey)
        responses = db.query(SurveyResponse).all()
        workbook = load_workbook(generate_survey_excel(s, responses, {}, lang="en"))
        assert workbook["Raw Responses"]["E2"].value == "=1+1"
        assert workbook["Raw Responses"]["E2"].data_type == "s"
    csrf = login(client)
    assert client.get(f"/admin/surveys/{survey}/results").status_code == 200
    assert client.get(f"/admin/surveys/{survey}/export/excel").status_code == 200

def test_csrf_get_delete_and_logout_revocation(client, survey):
    csrf = login(client)
    session = client.cookies.get("admin_session")
    assert client.get(f"/admin/surveys/{survey}/delete").status_code == 405
    assert client.post(f"/admin/surveys/{survey}/delete").status_code == 403
    assert client.post(f"/admin/surveys/{survey}/delete", data={"csrf_token": csrf},
                       headers={"origin":"https://evil.invalid"}).status_code == 403
    assert client.post("/admin/logout", data={"csrf_token": csrf}, follow_redirects=False).status_code == 303
    client.cookies.set("admin_session", session)
    assert client.get("/admin/dashboard", follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.get(Survey, survey) is not None

def test_invalid_editor_json_does_not_delete_questions(client, survey):
    csrf = login(client)
    result = client.post("/admin/surveys/save", data={"csrf_token": csrf, "survey_id": str(survey),
        "title_ar": "اختبار", "title_en": "Test", "questions_json": "{"})
    assert result.status_code == 400
    with SessionLocal() as db:
        assert db.query(SurveyQuestion).filter_by(survey_id=survey).count() == 2

def test_duplicate_editor_keys_rejected(client, survey):
    csrf = login(client)
    q = {"key":"q_1","text_ar":"نص","text_en":"Text","question_type":"text","is_required":True,"options":[]}
    result = client.post("/admin/surveys/save", data={"csrf_token":csrf,"title_ar":"اختبار","title_en":"Test",
        "questions_json":json.dumps([q,q])})
    assert result.status_code == 400

def test_redirect_and_security_headers(client):
    response = client.get("/set-language", params={"lang":"en","redirect":"//evil.invalid"}, follow_redirects=False)
    assert response.headers["location"] == "/"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"

def test_invalid_image_is_not_saved(tmp_path):
    with pytest.raises(ValueError):
        optimize_and_save_image(io.BytesIO(b"not an image"), tmp_path)
    assert not list(tmp_path.iterdir())

def test_rate_limit_persists_across_clients(client, survey):
    for _ in range(60):
        assert client.post("/s/test123/verify-employee", data={"employee_id":"999"}).status_code == 200
    response = client.post("/s/test123/verify-employee", data={"employee_id":"00123"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0

def test_concurrent_submission_has_one_response(client, survey):
    token = create_participation_token("test123","00123")
    def submit(_):
        return client.post("/s/test123/submit", data={"participation_token":token,"q_1":"opt_1"}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(code == 200 for code in pool.map(submit, range(8)))
    with SessionLocal() as db:
        assert db.query(SurveyResponse).count() == 1

def test_health_does_not_require_active_roster(client):
    assert client.get("/health").status_code == 200
    with SessionLocal() as db:
        db.query(Employee).update({"active":False})
        db.commit()
    assert client.get("/health").status_code == 200

def test_successful_editor_create_and_delete(client):
    csrf = login(client)
    question = {"key":"q_1","text_ar":"اختبار","text_en":"Test","question_type":"text",
                "is_required":True,"options":[]}
    response = client.post("/admin/surveys/save", data={"csrf_token":csrf,
        "title_ar":"استبيان","title_en":"Survey","questions_json":json.dumps([question])},
        follow_redirects=False)
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        survey_id = db.query(Survey).one().id
    assert client.post(f"/admin/surveys/{survey_id}/status",
        data={"csrf_token":csrf,"status_val":"published"}, follow_redirects=False).status_code == 303
    assert client.post(f"/admin/surveys/{survey_id}/delete",
        data={"csrf_token":csrf}, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.get(Survey, survey_id) is None
        assert db.query(SurveyQuestion).count() == 0

def test_image_valid_resize_and_oversize(tmp_path):
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB",(2400,1200),"white").save(image,"PNG")
    filename = optimize_and_save_image(image,tmp_path,max_dimension=1000)
    with Image.open(tmp_path / filename) as result:
        assert result.size == (1000,500)
        assert result.format == "WEBP"
    with pytest.raises(ValueError):
        optimize_and_save_image(io.BytesIO(b"x" * (10 * 1024 * 1024 + 1)),tmp_path)

def test_expired_admin_session_denied(client):
    from datetime import timedelta
    login(client)
    with SessionLocal() as db:
        db.query(AdminSession).update({"expires_at":datetime.utcnow()-timedelta(seconds=1)})
        db.commit()
    assert client.get("/admin/dashboard",follow_redirects=False).status_code == 303

def test_secure_cookies_on_https(client, monkeypatch):
    monkeypatch.setattr(settings, "BASE_URL", "https://testserver")
    with TestClient(app, base_url="https://testserver") as browser:
        response = browser.get("/admin/login")
        assert "Secure" in response.headers["set-cookie"]
        csrf = browser.cookies.get("csrf_token")
        response = browser.post("/admin/login",data={"username":settings.ADMIN_USERNAME,
            "password":settings.ADMIN_PASSWORD,"csrf_token":csrf},follow_redirects=False)
        assert response.status_code == 303
        assert "Secure" in response.headers["set-cookie"]


def test_invalid_unicode_csrf_is_rejected_cleanly(client):
    client.get("/admin/login")
    response = client.post("/admin/login", data={"username":"admin","password":"wrong",
                           "csrf_token":"رمز غير صالح"})
    assert response.status_code == 403


def audience_form(csrf, survey_id=None, mode="custom"):
    q = {"key":"q_1","text_ar":"سؤال","text_en":"Question","question_type":"text",
         "is_required":True,"options":[]}
    result = {"csrf_token":csrf,"title_ar":"مخصص","title_en":"Custom",
              "questions_json":json.dumps([q]),"audience_mode":mode}
    if survey_id is not None:
        result["survey_id"] = str(survey_id)
    return result

def test_audience_upload_and_survey_isolation(client, survey):
    from app.models import SurveyAudience
    csrf = login(client)
    with SessionLocal() as db:
        db.add(Employee(employee_id="00999",active=True)); db.commit()
    response = client.post("/admin/surveys/save",data=audience_form(csrf),
        files={"audience_file":("list.csv","Employee No.\n00123\n٠٠١٢٣\n","text/csv")},follow_redirects=False)
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        custom = db.query(Survey).filter_by(title_en="Custom").one()
        custom.status = "published"
        public_id, custom_id = custom.public_id, custom.id
        db.commit()
        assert db.query(SurveyAudience).filter_by(survey_id=custom_id).count() == 1
    assert client.post(f"/s/{public_id}/verify-employee",data={"employee_id":"00123"}).status_code == 200
    assert client.post(f"/s/{public_id}/verify-employee",data={"employee_id":"00999"}).status_code == 400
    assert client.post("/s/test123/verify-employee",data={"employee_id":"00999"}).status_code == 200
    token = create_participation_token(public_id,"00999")
    assert client.post(f"/s/{public_id}/submit",data={"participation_token":token,"q_1":"hello"}).status_code == 401
    html = client.get(f"/admin/surveys/{custom_id}/edit").text
    assert 'name="audience_file"' in html
    assert "00123" not in html  # Audience numbers are not embedded in the page.

@pytest.mark.parametrize("payload", ["wrong header\n00123\n","Employee No.\n","Employee No.\n1.23e4\n"])
def test_invalid_audience_upload_is_atomic(client, survey, payload):
    from app.models import SurveyAudience
    csrf = login(client)
    with SessionLocal() as db:
        db.get(Survey,survey).audience_mode="custom"
        db.add(SurveyAudience(survey_id=survey,employee_id="00123")); db.commit()
    response = client.post("/admin/surveys/save",data=audience_form(csrf,survey),
        files={"audience_file":("list.csv",payload,"text/csv")})
    assert response.status_code == 400, response.text
    assert 'id="survey-form"' in response.text
    assert 'value="Custom"' in response.text
    with SessionLocal() as db:
        assert db.get(Survey,survey).title_en == "Test"
        assert db.query(SurveyQuestion).filter_by(survey_id=survey).count() == 2
        assert db.get(SurveyAudience,(survey,"00123")) is not None

def test_custom_audience_requires_file(client):
    csrf=login(client)
    response=client.post("/admin/surveys/save",data=audience_form(csrf))
    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.query(Survey).count()==0

def test_audience_replace_keep_and_switch_to_all(client, survey):
    from app.models import SurveyAudience
    csrf=login(client)
    with SessionLocal() as db:
        db.add(Employee(employee_id="00999",active=True))
        db.get(Survey,survey).audience_mode="custom"
        db.add(SurveyAudience(survey_id=survey,employee_id="00123"))
        db.commit()
    old_token=create_participation_token("test123","00123")
    data=audience_form(csrf,survey)
    assert client.post("/admin/surveys/save",data=data,follow_redirects=False).status_code==303
    with SessionLocal() as db:
        assert db.get(SurveyAudience,(survey,"00123")) is not None
    assert client.post("/admin/surveys/save",data=data,
        files={"audience_file":("list.csv","Employee No.\n00999\n","text/csv")},
        follow_redirects=False).status_code==303
    assert client.post("/s/test123/submit",data={"participation_token":old_token,"q_1":"text"}).status_code==401
    token=create_participation_token("test123","00999")
    assert client.post("/s/test123/submit",data={"participation_token":token,"q_1":"text"}).status_code==200
    # Changing audience after participation keeps the response and locked question structure.
    assert client.post("/admin/surveys/save",data=audience_form(csrf,survey,"all"),
                       follow_redirects=False).status_code==303
    with SessionLocal() as db:
        assert db.get(Survey,survey).audience_mode=="all"
        assert db.query(SurveyAudience).filter_by(survey_id=survey).count()==0
        assert db.query(SurveyResponse).filter_by(survey_id=survey).count()==1
    assert client.post("/s/test123/verify-employee",data={"employee_id":"00123"}).status_code==200

def test_duplicate_copies_audience_and_delete_cascades(client,survey):
    from app.models import SurveyAudience
    csrf=login(client)
    with SessionLocal() as db:
        db.get(Survey,survey).audience_mode="custom"
        db.add(SurveyAudience(survey_id=survey,employee_id="00123")); db.commit()
    assert client.post(f"/admin/surveys/{survey}/duplicate",data={"csrf_token":csrf},
                       follow_redirects=False).status_code==303
    with SessionLocal() as db:
        copy=db.query(Survey).filter(Survey.id!=survey).one()
        copy_id=copy.id
        assert copy.audience_mode=="custom"
        assert db.get(SurveyAudience,(copy_id,"00123")) is not None
    assert client.post(f"/admin/surveys/{survey}/delete",data={"csrf_token":csrf},
                       follow_redirects=False).status_code==303
    with SessionLocal() as db:
        assert db.get(SurveyAudience,(survey,"00123")) is None
        assert db.get(SurveyAudience,(copy_id,"00123")) is not None

def test_audience_upload_csrf_and_template_auth(client):
    response=client.get("/admin/surveys/audience-template",follow_redirects=False)
    assert response.status_code==303
    csrf=login(client)
    template=client.get("/admin/surveys/audience-template")
    assert template.status_code==200
    assert template.content.decode("utf-8-sig").strip()=="Employee No."
    data=audience_form(csrf); data.pop("csrf_token")
    assert client.post("/admin/surveys/save",data=data,
        files={"audience_file":("list.csv","Employee No.\n00123\n","text/csv")}).status_code==403


def test_audience_malformed_large_field_rejected(client):
    csrf=login(client)
    response=client.post("/admin/surveys/save",data=audience_form(csrf),
        files={"audience_file":("bad.csv","Employee No.\n"+"1"*150000+"\n","text/csv")})
    assert response.status_code==400
    with SessionLocal() as db:
        assert db.query(Survey).count()==0


def test_open_survey_without_any_employee_records(client,survey):
    with SessionLocal() as db:
        db.execute(delete(Employee)); db.commit()
    assert client.get("/health").status_code == 200
    response=client.post("/s/test123/verify-employee",data={"employee_id":"008888"})
    assert response.status_code==200
    token=response.json()["token"]
    assert client.post("/s/test123/submit",data={"participation_token":token,"q_1":"opt_1"}).status_code==200
    with SessionLocal() as db:
        assert db.query(SurveyResponse).one().employee_id=="008888"

def test_custom_list_independent_of_central_roster(client):
    from app.models import SurveyAudience
    csrf=login(client)
    with SessionLocal() as db:
        db.execute(delete(Employee)); db.commit()
    response=client.post("/admin/surveys/save",data=audience_form(csrf),
        files={"audience_file":("list.csv","Employee No.\n007777\n","text/csv")},
        follow_redirects=False)
    assert response.status_code==303,response.text
    with SessionLocal() as db:
        survey=db.query(Survey).one()
        survey.status="published"
        public_id=survey.public_id
        db.commit()
    allowed=client.post(f"/s/{public_id}/verify-employee",data={"employee_id":"007777"})
    assert allowed.status_code==200
    assert client.post(f"/s/{public_id}/verify-employee",data={"employee_id":"008888"}).status_code==400
    assert client.post(f"/s/{public_id}/submit",data={
        "participation_token":allowed.json()["token"],"q_1":"answer"}).status_code==200

def test_new_survey_no_upload_defaults_to_unrestricted(client):
    csrf=login(client)
    data=audience_form(csrf,mode="all")
    data.pop("audience_mode")
    response=client.post("/admin/surveys/save",data=data,follow_redirects=False)
    assert response.status_code==303
    with SessionLocal() as db:
        assert db.query(Survey).one().audience_mode=="all"
