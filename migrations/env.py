"""Окружение Alembic.

Подключение берётся из приложения (app.database.engine), поэтому адрес базы
задаётся в одном месте — переменной DATABASE_URL. Тесты могут передать своё
подключение через config.attributes["connection"].
"""

from alembic import context

from app import models  # noqa: F401  — регистрирует таблицы в Base.metadata
from app.database import Base, engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.begin() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite не умеет ALTER COLUMN — Alembic пересоздаёт таблицу целиком
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
