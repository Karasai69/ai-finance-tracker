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


def test_existing_database_without_alembic_is_stamped(tmp_path):
    """База, созданная через create_all до появления миграций, сохраняет данные."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (email, password_hash) VALUES ('a@b.kz', 'x')"))
    with engine.begin() as connection:
        run_migrations(connection)
    with engine.connect() as connection:
        assert inspect(connection).has_table("alembic_version")
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
