from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    company: str
    location: str
    url: str
    date_found: datetime = Field(default_factory=datetime.now)

    description: Optional[str] = Field(default=None)
    salary: Optional[str] = Field(default=None)
    is_remote: bool = Field(default=False)

    # --- Source Platform Metadata ---
    seniority: Optional[str] = Field(default=None)
    modality: Optional[str] = Field(default=None)
    tags: Optional[str] = Field(default=None)
    source_platform: Optional[str] = Field(default=None)

    # --- AI Analysis Layer ---
    ai_match_score: Optional[int] = Field(default=None)
    ai_summary: Optional[str] = Field(default=None)
    recommended_profile: Optional[str] = Field(default=None)  # "backend" | "frontend" | "backend_ai"
    is_suitable: Optional[bool] = Field(default=None)
    seniority_mismatch: Optional[bool] = Field(default=None)
    missing_skills: Optional[str] = Field(default=None)  # JSON string list

    # --- Pipeline Status ---
    cv_generated: bool = Field(default=False)
    cv_path: Optional[str] = Field(default=None)
    email_sent: bool = Field(default=False)
    notified: bool = Field(default=False)
