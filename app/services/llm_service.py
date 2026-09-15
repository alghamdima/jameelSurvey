import json
import logging
from typing import Optional
import httpx
from app.core.config import settings
from app.schemas.llm import LLMSurveyOutput

logger = logging.getLogger(__name__)

class LLMService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())

    @staticmethod
    async def generate_survey_from_prompt(prompt: str) -> LLMSurveyOutput:
        """
        توليد مسودة استبيان ثنائي اللغة بالاعتماد على نموذج LLM متوافق مع OpenAI API
        مع التحقق الصارم من صحة المخطط عبر Pydantic.
        """
        if not LLMService.is_configured():
            raise ValueError("LLM_NOT_CONFIGURED")

        system_instruction = (
            "You are an expert HR and corporate survey designer for Abdul Latif Jameel Finance. "
            "Generate an engaging, professional, bilingual (Arabic & English) survey based on the user's prompt. "
            "Return STRICT JSON matching the following schema:\n"
            "{\n"
            '  "title_ar": "string",\n'
            '  "title_en": "string",\n'
            '  "description_ar": "string",\n'
            '  "description_en": "string",\n'
            '  "questions": [\n'
            "    {\n"
            '      "key": "q_1",\n'
            '      "question_type": "single_choice" | "multiple_choice" | "text",\n'
            '      "text_ar": "string",\n'
            '      "text_en": "string",\n'
            '      "is_required": true,\n'
            '      "options": [\n'
            '        {"key": "opt_1", "text_ar": "نعم", "text_en": "Yes"},\n'
            '        {"key": "opt_2", "text_ar": "لا", "text_en": "No"}\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "All question keys MUST be simple identifiers like q_1, q_2. Option keys MUST be opt_1, opt_2. "
            "Options array is required for single_choice and multiple_choice, and must be empty/null for text. "
            "Do NOT include markdown formatting or backticks around the json."
        )

        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"LLM API error {resp.status_code}: {resp.text}")
                raise RuntimeError(f"LLM provider error: {resp.status_code}")
            
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # تنظيف أي كتل كود markdown إن وجدت مثل ```json ... ```
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content_clean = "\n".join(lines).strip()
            
            parsed_json = json.loads(content_clean)
            
            # التحقق الصارم عبر Pydantic
            validated = LLMSurveyOutput.model_validate(parsed_json)
            return validated
