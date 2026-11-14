import os
import warnings

from dotenv import load_dotenv

load_dotenv()

DEV_SECRET = "dev-secret-change-me"


def normalize_database_url(url: str) -> str:
    """Neon и Render выдают адрес вида postgres://..., а SQLAlchemy нужен драйвер psycopg."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings:
    def __init__(self) -> None:
        database_url = (os.getenv("DATABASE_URL") or "").strip()
        if not database_url:
            # На Render файловая система временная: без внешней базы данные пропадут
            if os.getenv("RENDER"):
                raise RuntimeError(
                    "DATABASE_URL не задан. Добавьте строку подключения к PostgreSQL (Neon) "
                    "в Render → Environment."
                )
            database_url = "sqlite:///./finance.db"
        self.database_url = normalize_database_url(database_url)

        # Любой провайдер с OpenAI-совместимым API (Groq, Google Gemini, OpenAI и др.)
        self.ai_api_key = os.getenv("AI_API_KEY") or None
        self.ai_base_url = os.getenv("AI_BASE_URL") or None
        self.ai_model = os.getenv("AI_MODEL") or None
        self.ai_timeout = float(os.getenv("AI_TIMEOUT", "20"))
        # Распознавание речи (Whisper). У Groq — whisper-large-v3, у OpenAI — whisper-1
        default_stt = None
        if "groq.com" in (self.ai_base_url or ""):
            default_stt = "whisper-large-v3"
        elif not self.ai_base_url:
            default_stt = "whisper-1"
        self.stt_model = os.getenv("STT_MODEL") or default_stt

        # Вход в аккаунт
        self.secret_key = os.getenv("SECRET_KEY") or DEV_SECRET
        self.token_days = int(os.getenv("TOKEN_DAYS", "30"))
        # На сайте с https включите COOKIE_SECURE=true
        self.cookie_secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"

        if self.secret_key == DEV_SECRET:
            warnings.warn("SECRET_KEY не задан: используется ключ для разработки. На сервере задайте свой.")

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_api_key and self.ai_model)

    @property
    def stt_enabled(self) -> bool:
        return bool(self.ai_api_key and self.stt_model)


settings = Settings()
