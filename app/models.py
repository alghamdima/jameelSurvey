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
