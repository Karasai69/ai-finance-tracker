"""Применение миграций при старте приложения."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import engine

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "0001"


def alembic_config(connection=None) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def check_old_schema(tables) -> None:
    """База из самой первой версии (без аккаунтов) не подходит: в ней нет user_id."""
    if tables.has_table("transactions"):
        columns = {col["name"] for col in tables.get_columns("transactions")}
        if "user_id" not in columns:
            raise RuntimeError(
                "База данных создана старой версией приложения (без аккаунтов). "
                "Удалите файл finance.db и запустите снова."
            )


def run_migrations(connection=None) -> None:
    bind = connection if connection is not None else engine
    tables = inspect(bind)
    check_old_schema(tables)
    cfg = alembic_config(connection)
    # База создана до появления миграций (таблицы есть, учёта версий нет):
    # отмечаем её как начальную версию, данные не трогаем.
    if tables.has_table("users") and not tables.has_table("alembic_version"):
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
