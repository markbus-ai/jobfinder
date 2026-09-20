import logging

from sqlalchemy import inspect, text
from sqlmodel import create_engine, SQLModel, Session

from core.config import settings
from models.JobModels import Job  # noqa: F401  (registers the table in SQLModel.metadata)

logger = logging.getLogger(__name__)

engine = create_engine(settings.DATABASE_URL, echo=settings.DATABASE_ECHO)


def _add_missing_columns() -> list[str]:
    """
    Idempotently add columns that exist on the model but not in the DB.

    ``SQLModel.metadata.create_all`` only creates missing tables; it never ALTERs
    an existing table. Production already has a populated DB, so every new model
    field needs an explicit ``ALTER TABLE ... ADD COLUMN`` guarded by an
    inspection of the live schema. Safe to call on every startup.
    """
    inspector = inspect(engine)
    table_name = Job.__tablename__
    if table_name not in inspector.get_table_names():
        return []

    existing = {column["name"] for column in inspector.get_columns(table_name)}
    added: list[str] = []
    for column in Job.__table__.columns:
        if column.name in existing:
            continue
        column_type = column.type.compile(dialect=engine.dialect)
        statement = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column_type}'
        with engine.begin() as connection:
            connection.execute(text(statement))
        added.append(column.name)
        logger.info("Migration: added column %s.%s (%s)", table_name, column.name, column_type)
    return added


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
