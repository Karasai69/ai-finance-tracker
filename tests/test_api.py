"""Тесты API. Ключ к ИИ не нужен — работает простой разбор."""


# ---------- Вход в аккаунт ----------

def test_register_login_me_logout(make_client):
    c = make_client()
    r = c.post("/api/auth/register", json={"email": " Aidar@Example.com ", "password": "password123"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "aidar@example.com"
    assert "access_token" in r.cookies or c.cookies.get("access_token")

    assert c.get("/api/auth/me").json()["email"] == "aidar@example.com"

    assert c.post("/api/auth/logout").status_code == 204
    c.cookies.clear()
    assert c.get("/api/auth/me").status_code == 401

    r = c.post("/api/auth/login", json={"email": "aidar@example.com", "password": "password123"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_bearer_token_works_without_cookie(make_client):
    c = make_client()
    token = c.post("/api/auth/register", json={"email": "a@b.kz", "password": "password123"}).json()["access_token"]
    c.cookies.clear()
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_wrong_password_and_duplicate_email(make_client):
    c = make_client()
    c.post("/api/auth/register", json={"email": "a@b.kz", "password": "password123"})
    assert c.post("/api/auth/register", json={"email": "a@b.kz", "password": "password123"}).status_code == 409
    assert c.post("/api/auth/login", json={"email": "a@b.kz", "password": "wrongpass1"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "no@b.kz", "password": "password123"}).status_code == 401


def test_bad_registration_data(make_client):
    c = make_client()
    assert c.post("/api/auth/register", json={"email": "not-email", "password": "password123"}).status_code == 422
    assert c.post("/api/auth/register", json={"email": "a@b.kz", "password": "short"}).status_code == 422


def test_data_requires_login(make_client):
    c = make_client()
    assert c.get("/api/transactions").status_code == 401
    assert c.get("/api/summary").status_code == 401
    assert c.post("/api/parse", json={"text": "такси 300"}).status_code == 401
    assert c.get("/api/export.csv").status_code == 401


def test_users_see_only_their_own_data(make_client):
    alice, bob = make_client(), make_client()
    alice.post("/api/auth/register", json={"email": "alice@kz.kz", "password": "password123"})
    bob.post("/api/auth/register", json={"email": "bob@kz.kz", "password": "password123"})

    item = {"date": "2026-11-10", "amount": 300, "category": "transport", "description": "такси"}
    row = alice.post("/api/transactions", json={"items": [item]}).json()[0]

    assert bob.get("/api/transactions", params={"month": "2026-11"}).json() == []
    assert bob.get("/api/summary", params={"month": "2026-11"}).json()["expense"] == 0
    assert bob.delete(f"/api/transactions/{row['id']}").status_code == 404
    assert bob.patch(f"/api/transactions/{row['id']}", json={"amount": 1}).status_code == 404
    assert len(alice.get("/api/transactions", params={"month": "2026-11"}).json()) == 1


# ---------- Записи ----------

def test_parse_save_list_summary_delete(client):
    parsed = client.post("/api/parse", json={"text": "такси 300, брат прислал 10000", "date": "2026-11-10"})
    assert parsed.status_code == 200
    body = parsed.json()
    assert body["source"] == "rules"
    assert len(body["items"]) == 2

    saved = client.post("/api/transactions", json={"items": body["items"], "raw_text": "test"})
    assert saved.status_code == 201
    ids = [row["id"] for row in saved.json()]

    assert len(client.get("/api/transactions", params={"month": "2026-11"}).json()) == 2

    summary = client.get("/api/summary", params={"month": "2026-11"}).json()
    assert summary["income"] == 10000
    assert summary["expense"] == 300
    assert summary["balance"] == 9700

    assert client.get("/api/transactions", params={"month": "2026-10"}).json() == []

    assert client.delete(f"/api/transactions/{ids[0]}").status_code == 204
    assert len(client.get("/api/transactions", params={"month": "2026-11"}).json()) == 1


def test_update_category_changes_kind(client):
    item = {"date": "2026-11-10", "amount": 5000, "category": "other", "description": "Султан"}
    row = client.post("/api/transactions", json={"items": [item]}).json()[0]
    updated = client.patch(f"/api/transactions/{row['id']}", json={"category": "lend"}).json()
    assert updated["kind"] == "lend"


def test_export_csv(client):
    item = {"date": "2026-11-10", "amount": 300, "category": "transport", "description": "такси"}
    client.post("/api/transactions", json={"items": [item]})
    response = client.get("/api/export.csv", params={"month": "2026-11"})
    assert response.status_code == 200
    assert "Транспорт и такси" in response.text


def test_bad_month_is_rejected(client):
    assert client.get("/api/summary", params={"month": "2026-13"}).status_code == 422


def test_public_pages(make_client):
    c = make_client()
    assert c.get("/").status_code == 200
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/api/categories").status_code == 200


def test_import_csv(client):
    text = "Дата;Тип;Категория;Сумма;Описание\n01.11.2026;;Транспорт и такси;660;такси\n02.11.2026;;Доход;15000;от брата\n"
    r = client.post("/api/import", json={"csv": text})
    assert r.status_code == 201
    assert r.json() == {"imported": 2, "months": ["2026-11"]}
    assert client.get("/api/summary", params={"month": "2026-11"}).json()["income"] == 15000

    bad = client.post("/api/import", json={"csv": "01.11.2026;;Казино;100"})
    assert bad.status_code == 422
    assert len(client.get("/api/transactions", params={"month": "2026-11"}).json()) == 2


def test_login_is_rate_limited(make_client):
    c = make_client()
    c.post("/api/auth/register", json={"email": "a@b.kz", "password": "password123"})
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": "a@b.kz", "password": "wrongpass1"}).status_code == 401
    blocked = c.post("/api/auth/login", json={"email": "a@b.kz", "password": "password123"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    # другой email с того же адреса не заблокирован
    assert c.post("/api/auth/login", json={"email": "x@b.kz", "password": "password123"}).status_code == 401
