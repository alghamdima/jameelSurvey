from typing import List, Optional
from pydantic import BaseModel, Field

class LLMQuestionOption(BaseModel):
    key: str = Field(..., description="معرف الخيار الثابت مثل opt_1")
    text_ar: str = Field(..., min_length=1, max_length=200, description="نص الخيار بالعربية")
    text_en: str = Field(..., min_length=1, max_length=200, description="نص الخيار بالإنجليزية")

class LLMQuestion(BaseModel):
    key: str = Field(..., description="معرف السؤال الثابت مثل q_1")
    question_type: str = Field(..., pattern="^(single_choice|multiple_choice|text)$", description="نوع السؤال")
    text_ar: str = Field(..., min_length=3, max_length=500, description="نص السؤال بالعربية")
    text_en: str = Field(..., min_length=3, max_length=500, description="نص السؤال بالإنجليزية")
    is_required: bool = True
    options: Optional[List[LLMQuestionOption]] = Field(default=None, description="خيارات السؤال إذا كان اختيار من متعدد أو مفرد")

class LLMSurveyOutput(BaseModel):
    title_ar: str = Field(..., min_length=3, max_length=255, description="عنوان الاستبيان بالعربية")
    title_en: str = Field(..., min_length=3, max_length=255, description="عنوان الاستبيان بالإنجليزية")
    description_ar: Optional[str] = Field(None, max_length=1000, description="وصف الاستبيان بالعربية")
    description_en: Optional[str] = Field(None, max_length=1000, description="وصف الاستبيان بالإنجليزية")
    questions: List[LLMQuestion] = Field(..., min_items=1, max_items=25, description="قائمة الأسئلة المنشأة")
