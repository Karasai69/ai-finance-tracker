"""Общие настройки тестов.

Переменные окружения задаются ДО импорта приложения, поэтому тесты не трогают
вашу базу finance.db и не ходят к ИИ, даже если в .env есть ключ.
В GitHub Actions тесты запускаются на PostgreSQL через TEST_DATABASE_URL.
"""

import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["AI_API_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"


@pytest.fixture()
def make_client():
    """Фабрика клиентов: у каждого клиента свои cookie, то есть свой пользователь."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.database import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return lambda: TestClient(app)


@pytest.fixture()
def client(make_client):
    """Клиент, уже вошедший в аккаунт."""
    c = make_client()
    response = c.post("/api/auth/register", json={"email": "aidar@example.com", "password": "password123"})
    assert response.status_code == 201, response.text
    return c
