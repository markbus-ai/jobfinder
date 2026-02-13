from datetime import datetime, date
from typing import Optional, List
from sqlmodel import SQLModel, Field, JSON

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

    # --- Capa de Inteligencia ---
    ai_match_score: Optional[int] = Field(default=None)
    ai_summary: Optional[str] = Field(default=None)
    is_junior: Optional[bool] = Field(default=None)
    
    # Nuevos campos de auditoría
    is_suitable: Optional[bool] = Field(default=None)
    seniority_mismatch: Optional[bool] = Field(default=None)
    missing_skills: Optional[str] = Field(default=None)  # Guardaremos la lista como JSON string

    notified: bool = Field(default=False)

class Message(SQLModel, table=True):
    id: str = Field(primary_key=True)
    text: str
    date: date