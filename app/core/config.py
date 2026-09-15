from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    APP_NAME: str = "عبد اللطيف جميل للتمويل"
    APP_ENV: str = "production"
    DEBUG: bool = Field(False, validation_alias="SURVEY_DEBUG")
    SECRET_KEY: str = "dev-secret-key-please-replace-in-production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str = "http://localhost:8000"
    DATABASE_URL: str = "sqlite:///./data/surveys.db"
    DEFAULT_LOCALE: str = "ar"
    SUPPORTED_LOCALES: list[str] = ["ar", "en"]

    # إعدادات الأدمن الافتراضية
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    ADMIN_SESSION_TTL_SECONDS: int = 60 * 60 * 8
    PARTICIPATION_TTL_SECONDS: int = 60 * 60 * 12
    EMPLOYEE_CSV_PATH: str = ""

    @property
    def cookie_secure(self) -> bool:
        return self.BASE_URL.lower().startswith("https://")

    def validate_runtime(self) -> None:
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY in {
            "dev-secret-key-please-replace-in-production",
            "change-this-to-a-secure-random-secret-key-min-32-chars",
        }:
            raise ValueError("Configure a unique random SECRET_KEY of at least 32 characters")
        if len(self.ADMIN_PASSWORD) < 12 or self.ADMIN_PASSWORD in {"admin123", "change_this_secure_password"}:
            raise ValueError("Configure a unique ADMIN_PASSWORD of at least 12 characters")
        if self.ADMIN_SESSION_TTL_SECONDS <= 0 or self.PARTICIPATION_TTL_SECONDS <= 0:
            raise ValueError("Session durations must be positive")

    # إعدادات LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


    @property
    def base_path(self) -> str:
        import urllib.parse
        return urllib.parse.urlparse(self.BASE_URL).path.rstrip('/')

    def url_for_app(self, path: str) -> str:
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        path = path if path.startswith("/") else "/" + path
        bp = self.base_path
        if bp:
            if path == bp or path.startswith(bp + "/"):
                return path
            return f"{bp}{path}"
        return path

settings = Settings()
