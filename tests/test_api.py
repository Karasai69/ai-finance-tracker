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


def test_index_links_versioned_assets_and_is_not_cached(make_client):
    r = make_client().get("/")
    assert r.headers["cache-control"] == "no-cache"
    assert "/static/app.js?v=" in r.text and "/static/style.css?v=" in r.text


# ---------- Долги, лимиты, сравнение ----------

def _save(client, *items):
    r = client.post("/api/transactions", json={"items": list(items)})
    assert r.status_code == 201, r.text
    return r.json()


def test_debts_by_person_across_months(client):
    _save(
        client,
        {"date": "2026-10-20", "amount": 10000, "category": "lend", "counterparty": "Султан"},
        {"date": "2026-11-09", "amount": 22000, "category": "lend", "counterparty": "Алижан"},
        {"date": "2026-11-10", "amount": 4000, "category": "repaid", "counterparty": "султан"},
        {"date": "2026-11-11", "amount": 22000, "category": "repaid", "counterparty": "Алижан"},
    )
    debts = {d["person"]: d for d in client.get("/api/debts").json()}
    assert debts["Султан"]["balance"] == 6000
    assert debts["Султан"]["since"] == "2026-10-20"
    assert debts["Алижан"]["balance"] == 0

    summary = client.get("/api/summary", params={"month": "2026-11"}).json()
    assert summary["lent"] == 22000 and summary["repaid"] == 26000
    assert summary["balance"] == 4000  # 0 доходов - 0 расходов - 22000 + 26000


def test_counterparty_only_for_debts(client):
    row = _save(client, {"date": "2026-11-10", "amount": 300, "category": "transport", "counterparty": "Али"})[0]
    assert row["counterparty"] is None
    updated = client.patch(f"/api/transactions/{row['id']}", json={"category": "lend", "counterparty": "Али"}).json()
    assert updated["kind"] == "lend" and updated["counterparty"] == "Али"


def test_budgets_set_update_delete_and_in_summary(client):
    assert client.put("/api/budgets/income", json={"limit": 100}).status_code == 400
    assert client.put("/api/budgets/transport", json={"limit": 10000}).json()[0]["limit"] == 10000
    assert client.put("/api/budgets/transport", json={"limit": 8000}).json()[0]["limit"] == 8000
    client.put("/api/budgets/cafe", json={"limit": 5000})
    _save(client, {"date": "2026-11-10", "amount": 9000, "category": "transport"})

    cats = {c["category"]: c for c in client.get("/api/summary", params={"month": "2026-11"}).json()["by_category"]}
    assert cats["transport"]["limit"] == 8000 and cats["transport"]["total"] == 9000
    assert cats["cafe"]["total"] == 0 and cats["cafe"]["limit"] == 5000  # лимит без трат тоже виден

    assert client.put("/api/budgets/transport", json={"limit": None}).json() == [
        {"category": "cafe", "name": "Кафе и перекусы", "limit": 5000}
    ]


def test_summary_compares_with_previous_month(client):
    _save(
        client,
        {"date": "2026-09-05", "amount": 1000, "category": "products"},
        {"date": "2026-10-05", "amount": 3000, "category": "products"},
        {"date": "2026-10-06", "amount": 500, "category": "transport"},
    )
    summary = client.get("/api/summary", params={"month": "2026-10"}).json()
    assert summary["prev_month"] == "2026-09" and summary["compare_days"] is None
    assert summary["expense_to_date"] == 3500 and summary["prev_expense"] == 1000
    cats = {c["category"]: c for c in summary["by_category"]}
    assert cats["products"]["prev_total"] == 1000 and cats["transport"]["prev_total"] == 0


def test_budgets_are_private(make_client):
    a, b = make_client(), make_client()
    a.post("/api/auth/register", json={"email": "a@kz.kz", "password": "password123"})
    b.post("/api/auth/register", json={"email": "b@kz.kz", "password": "password123"})
    a.put("/api/budgets/transport", json={"limit": 1000})
    assert b.get("/api/budgets").json() == []
