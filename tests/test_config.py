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
