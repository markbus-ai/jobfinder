from sqlmodel import create_engine, SQLModel, Session
from core.config import settings

engine = create_engine(settings.DATABASE_URL, echo=settings.DATABASE_ECHO)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
