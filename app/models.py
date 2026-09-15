from datetime import datetime
import json
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db.base import Base

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(32), unique=True, nullable=False, index=True)
    title_ar = Column(String(255), nullable=False)
    title_en = Column(String(255), nullable=False)
    description_ar = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    status = Column(String(20), default="draft", nullable=False)  # draft, published, closed
    audience_mode = Column(String(20), default="all", nullable=False)
    audience = relationship("SurveyAudience", cascade="all, delete-orphan")
    theme_style = Column(String(30), default="creative", nullable=False)  # creative, classic
    header_image_url = Column(String(500), nullable=True)  # صورة رئيسية للاستبيان
    background_url = Column(String(500), nullable=True)  # صورة أو لون خلفية الصفحة
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    questions = relationship("SurveyQuestion", back_populates="survey", cascade="all, delete-orphan", order_by="SurveyQuestion.order_index")
    responses = relationship("SurveyResponse", back_populates="survey", cascade="all, delete-orphan")


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"

    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    question_key = Column(String(50), nullable=False)  # ثابت ومستقل عن اللغة مثل q_1
    text_ar = Column(Text, nullable=False)
    text_en = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False)  # single_choice, multiple_choice, text
    is_required = Column(Boolean, default=True)
    order_index = Column(Integer, default=0)

    # تخزين الخيارات في JSON: [{"key": "opt_1", "text_ar": "نعم", "text_en": "Yes"}, ...]
    options_json = Column(Text, nullable=True)

    survey = relationship("Survey", back_populates="questions")

    __table_args__ = (UniqueConstraint("survey_id", "question_key", name="uq_survey_question_key"),)

    def get_options(self) -> list[dict]:
        if not self.options_json:
            return []
        try:
            return json.loads(self.options_json)
        except Exception:
            return []


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False, index=True)  # نص للحفاظ على الأصفار في بدايته
    submitted_at = Column(DateTime, default=datetime.utcnow)

    # إجابات الموظف بتنسيق JSON: {"q_1": "opt_1", "q_2": ["opt_a", "opt_b"], "q_3": "نص الإجابة"}
    answers_json = Column(Text, nullable=False)

    survey = relationship("Survey", back_populates="responses")

    __table_args__ = (
        UniqueConstraint("survey_id", "employee_id", name="uq_survey_employee"),
    )


class Employee(Base):
    __tablename__ = "employees"
    employee_id = Column(String(50), primary_key=True)
    active = Column(Boolean, nullable=False, default=True)

class EmployeeImport(Base):
    __tablename__ = "employee_imports"
    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), nullable=False)
    row_count = Column(Integer, nullable=False)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id = Column(String(64), primary_key=True)
    admin_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)

class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    key = Column(String(64), primary_key=True)
    hits = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False, index=True)


class SurveyAudience(Base):
    __tablename__ = "survey_audience"
    survey_id = Column(Integer, ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True)
    employee_id = Column(String(50), primary_key=True)
