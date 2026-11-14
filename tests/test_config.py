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


def test_stt_model_defaults(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("AI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("STT_MODEL", raising=False)
    assert Settings().stt_model == "whisper-large-v3"
    monkeypatch.setenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    assert Settings().stt_model is None
    monkeypatch.setenv("STT_MODEL", "my-whisper")
    assert Settings().stt_model == "my-whisper"


def test_speech_extension():
    import pytest

    pytest.importorskip("openai")
    from app.parser.speech import extension_for

    assert extension_for("audio/webm;codecs=opus") == "webm"
    assert extension_for("audio/mp4") == "m4a"
    assert extension_for("") == "webm"
