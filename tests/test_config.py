from app.config import normalize_database_url


def test_postgres_urls_get_psycopg_driver():
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert (
        normalize_database_url("postgresql://u:p@h/db?sslmode=require")
        == "postgresql+psycopg://u:p@h/db?sslmode=require"
    )


def test_other_urls_unchanged():
    assert normalize_database_url("sqlite:///./finance.db") == "sqlite:///./finance.db"
    assert normalize_database_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"


def test_missing_database_url_on_render_is_explained(monkeypatch):
    import pytest

    from app.config import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="DATABASE_URL не задан"):
        Settings()


def test_missing_database_url_locally_falls_back_to_sqlite(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert Settings().database_url == "sqlite:///./finance.db"
