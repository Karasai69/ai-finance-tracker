"""Миграции создают ту же схему, что описана в моделях, и не ломают старую базу."""

import pytest

pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.database import Base  # noqa: E402
from app.migrate import run_migrations  # noqa: E402


def test_migrations_match_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        run_migrations(connection)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"Модели и миграции расходятся, создайте новую миграцию: {diff}"


def test_database_created_before_migrations_keeps_data(tmp_path):
    """База, созданная через create_all до появления миграций (схема версии 0001):
    помечается начальной версией, обновляется до последней и сохраняет данные."""
    from alembic import command

    from app.migrate import alembic_config

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0001")
        connection.execute(text("DROP TABLE alembic_version"))  # как будто миграций ещё не было
        connection.execute(text("INSERT INTO users (id, email, password_hash) VALUES (1, 'a@b.kz', 'x')"))
        connection.execute(text(
            "INSERT INTO transactions (user_id, date, amount, category, kind, description) "
            "VALUES (1, '2026-11-09', 22000, 'lend', 'lend', 'Алижан')"
        ))

    with engine.begin() as connection:
        run_migrations(connection)

    with engine.connect() as connection:
        assert inspect(connection).has_table("budgets")
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
        # имя должника перенесено из описания в новую колонку
        assert connection.execute(text("SELECT counterparty FROM transactions")).scalar() == "Алижан"


def test_ten_percent_becomes_savings(tmp_path):
    """Старые записи «10 процентов» после миграции считаются отложенными деньгами."""
    from alembic import command

    from app.migrate import alembic_config

    engine = create_engine(f"sqlite:///{tmp_path / 'ten.db'}")
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0003")
        connection.execute(text("INSERT INTO users (id, email, password_hash) VALUES (1, 'a@b.kz', 'x')"))
        connection.execute(text(
            "INSERT INTO transactions (user_id, date, amount, category, kind, description) VALUES "
            "(1, '2026-11-01', 17250, 'ten_percent', 'expense', '10%'), "
            "(1, '2026-11-02', 900, 'cafe', 'expense', 'кофе')"
        ))
        connection.execute(text("INSERT INTO budgets (user_id, category, monthly_limit) VALUES (1, 'ten_percent', 20000)"))

    with engine.begin() as connection:
        run_migrations(connection)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT category, kind FROM transactions ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [("savings", "save"), ("cafe", "expense")]
        assert connection.execute(text("SELECT count(*) FROM budgets")).scalar() == 0
