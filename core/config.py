import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    PROJECT_NAME: str = "JobFinder"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///jobfinder.db")
    DATABASE_ECHO: bool = os.getenv("DATABASE_ECHO", "false").lower() == "true"

    # Groq API (key rotation — separated by comma)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEYS: str = os.getenv("GROQ_API_KEYS", "")
    if not GROQ_API_KEY and not GROQ_API_KEYS:
        raise ValueError("GROQ_API_KEY or GROQ_API_KEYS environment variable is required")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    # Telegram (Optional)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Search configuration
    SEARCH_TERMS: str = os.getenv("SEARCH_TERMS", "python developer,fastapi developer,backend developer,react developer,frontend developer,ai engineer,llm developer")
    SEARCH_SOURCES: str = os.getenv("SEARCH_SOURCES", "getonboard,linkedin,indeed,google")

    # GetOnBoard configuration
    GETONBOARD_ENABLED: bool = os.getenv("GETONBOARD_ENABLED", "true").lower() == "true"
    GETONBOARD_PER_PAGE: int = int(os.getenv("GETONBOARD_PER_PAGE", "50"))

    # Candidate profile
    CANDIDATE_NAME: str = os.getenv("CANDIDATE_NAME", "Marcos Bustos")
    CANDIDATE_EMAIL: str = os.getenv("CANDIDATE_EMAIL", "marcosbustos.dev@gmail.com")
    CANDIDATE_LOCATION: str = os.getenv("CANDIDATE_LOCATION", "Mar del Plata, Argentina")

    # CV generation
    CV_OUTPUT_DIR: str = os.getenv("CV_OUTPUT_DIR", "/tmp/jobfinder_cvs")

    # Email (SMTP) — fallback to config_smtp.json via EmailService
    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
    SENDER_NAME: str = os.getenv("SENDER_NAME", "Marcos Bustos")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))


settings = Settings()
