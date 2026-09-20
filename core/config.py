import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable robustly."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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
    SEARCH_TERMS: str = os.getenv("SEARCH_TERMS", "python developer,backend developer,fastapi developer,fullstack developer,ai engineer")
    SEARCH_SOURCES: str = os.getenv("SEARCH_SOURCES", "getonboard,linkedin")

    # GetOnBoard configuration
    GETONBOARD_ENABLED: bool = os.getenv("GETONBOARD_ENABLED", "true").lower() == "true"
    GETONBOARD_PER_PAGE: int = int(os.getenv("GETONBOARD_PER_PAGE", "50"))

    # Candidate profile
    CANDIDATE_NAME: str = os.getenv("CANDIDATE_NAME", "Marcos Bustos")
    CANDIDATE_EMAIL: str = os.getenv("CANDIDATE_EMAIL", "marcosbustos.dev@gmail.com")
    CANDIDATE_LOCATION: str = os.getenv("CANDIDATE_LOCATION", "Mar del Plata, Argentina")

    # Location eligibility policy
    CANDIDATE_CITY: str = os.getenv("CANDIDATE_CITY", "Mar del Plata")
    CANDIDATE_COUNTRY: str = os.getenv("CANDIDATE_COUNTRY", "Argentina")
    ALLOW_REMOTE: bool = env_bool("ALLOW_REMOTE", True)
    BLOCK_FOREIGN_RESTRICTED_REMOTE: bool = env_bool("BLOCK_FOREIGN_RESTRICTED_REMOTE", True)

    # Notification threshold (technical match score, 0-100)
    MIN_MATCH_SCORE: int = int(os.getenv("MIN_MATCH_SCORE", "70"))

    # Analysis retry: how many times a transiently failed job may be re-analyzed
    MAX_ANALYSIS_ATTEMPTS: int = int(os.getenv("MAX_ANALYSIS_ATTEMPTS", "3"))

    # CV generation
    CV_OUTPUT_DIR: str = os.getenv("CV_OUTPUT_DIR", "/tmp/jobfinder_cvs")

    # Email (SMTP) — fallback to config_smtp.json via EmailService
    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
    SENDER_NAME: str = os.getenv("SENDER_NAME", "Marcos Bustos")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))


settings = Settings()
