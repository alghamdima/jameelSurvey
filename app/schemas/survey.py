import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,49}$")
    text_ar: str = Field(min_length=1, max_length=200)
    text_en: str = Field(min_length=1, max_length=200)

class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,49}$")
    text_ar: str = Field(min_length=1, max_length=500)
    text_en: str = Field(min_length=1, max_length=500)
    question_type: Literal["single_choice", "multiple_choice", "text"]
    is_required: bool = Field(default=True, strict=True)
    options: list[Choice] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_choices(self):
        if self.key in {"participation_token", "csrf_token"}:
            raise ValueError("Reserved question key")
        if self.question_type == "text":
            self.options = []
        elif len(self.options) < 2:
            raise ValueError("Choice questions require at least two options")
        if len({o.key for o in self.options}) != len(self.options):
            raise ValueError("Duplicate option keys")
        return self

class SurveyQuestions(BaseModel):
    questions: list[Question] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Duplicate question keys")
        return self

def validate_answers(questions, form):
    answers = {}
    for q in questions:
        values = form.getlist(q.question_key)
        if any(not isinstance(v, str) for v in values):
            raise ValueError("Invalid answer type")
        if q.question_type == "multiple_choice":
            if len(values) != len(set(values)):
                raise ValueError("Repeated choice")
            allowed = {opt["key"] for opt in q.get_options()}
            if any(v not in allowed for v in values):
                raise ValueError("Unknown choice")
            value = values
        else:
            if len(values) > 1:
                raise ValueError("Only one answer is allowed")
            value = values[0].strip() if values else ""
            if q.question_type == "single_choice":
                if value and value not in {o["key"] for o in q.get_options()}:
                    raise ValueError("Unknown choice")
            elif q.question_type == "text":
                if len(value) > 10000 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
                    raise ValueError("Invalid or oversized text")
            else:
                raise ValueError("Unknown question type")
        if q.is_required and not value:
            raise ValueError("Required answer missing")
        answers[q.question_key] = value
    return answers