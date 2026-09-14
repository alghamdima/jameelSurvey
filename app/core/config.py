from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    APP_NAME: str = "عبد اللطيف جميل للتمويل"
    APP_ENV: str = "production"
    DEBUG: bool = False
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
