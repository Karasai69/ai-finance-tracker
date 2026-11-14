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


def test_parse_learns_from_corrections(client):
    row = _save(client, {"date": "2026-11-10", "amount": 900, "category": "products", "description": "шашлык"})[0]
    first = client.post("/api/parse", json={"text": "шашлык 900", "date": "2026-11-12"}).json()
    assert first["items"][0]["category"] == "products"  # так пользователь записал в прошлый раз

    client.patch(f"/api/transactions/{row['id']}", json={"category": "cafe"})  # исправил
    second = client.post("/api/parse", json={"text": "шашлык 1200", "date": "2026-11-12"}).json()
    assert second["items"][0]["category"] == "cafe"


def test_insights_without_ai(client):
    empty = client.post("/api/insights", params={"month": "2026-11"}).json()
    assert empty["source"] == "rules" and "расходов пока нет" in empty["points"][0]

    _save(client, {"date": "2026-11-10", "amount": 900, "category": "cafe", "description": "шашлык"})
    result = client.post("/api/insights", params={"month": "2026-11"}).json()
    assert result["source"] == "rules"
    assert "«Кафе и перекусы»" in result["points"][0]


def test_pwa_files(make_client):
    c = make_client()
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert "__VERSION__" not in sw.text and sw.headers["cache-control"] == "no-cache"
    version = c.get("/api/health").json()["version"]
    assert f'"{version}"' in sw.text

    manifest = c.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.json()["display"] == "standalone"
    for icon in manifest.json()["icons"]:
        assert c.get(icon["src"]).status_code == 200
    assert c.get("/favicon.ico").status_code == 200


# ---------- Смена пароля и удаление аккаунта ----------

def test_change_password_logs_out_other_devices(make_client):
    laptop, phone = make_client(), make_client()
    laptop.post("/api/auth/register", json={"email": "a@b.kz", "password": "password123"})
    phone.post("/api/auth/login", json={"email": "a@b.kz", "password": "password123"})

    bad = laptop.post("/api/auth/password", json={"current_password": "wrongpass1", "new_password": "newpass123"})
    assert bad.status_code == 403
    same = laptop.post("/api/auth/password", json={"current_password": "password123", "new_password": "password123"})
    assert same.status_code == 400
    short = laptop.post("/api/auth/password", json={"current_password": "password123", "new_password": "short"})
    assert short.status_code == 422

    ok = laptop.post("/api/auth/password", json={"current_password": "password123", "new_password": "newpass123"})
    assert ok.status_code == 200
    assert laptop.get("/api/auth/me").status_code == 200  # это устройство остаётся в аккаунте
    assert phone.get("/api/auth/me").status_code == 401  # старый токен больше не действует

    fresh = make_client()
    assert fresh.post("/api/auth/login", json={"email": "a@b.kz", "password": "password123"}).status_code == 401
    assert fresh.post("/api/auth/login", json={"email": "a@b.kz", "password": "newpass123"}).status_code == 200


def test_delete_account_removes_all_data(make_client):
    alice, bob = make_client(), make_client()
    alice.post("/api/auth/register", json={"email": "alice@kz.kz", "password": "password123"})
    bob.post("/api/auth/register", json={"email": "bob@kz.kz", "password": "password123"})
    item = {"date": "2026-11-10", "amount": 300, "category": "transport", "description": "такси"}
    alice.post("/api/transactions", json={"items": [item]})
    bob.post("/api/transactions", json={"items": [item]})
    assert alice.put("/api/budgets/transport", json={"limit": 5000}).status_code == 200

    wrong = alice.request("DELETE", "/api/auth/account", json={"password": "wrongpass1"})
    assert wrong.status_code == 403
    assert alice.request("DELETE", "/api/auth/account", json={"password": "password123"}).status_code == 204

    assert alice.get("/api/auth/me").status_code == 401
    again = make_client()
    assert again.post("/api/auth/login", json={"email": "alice@kz.kz", "password": "password123"}).status_code == 401
    # Email снова свободен, а старые записи не «воскресают»
    assert again.post("/api/auth/register", json={"email": "alice@kz.kz", "password": "password123"}).status_code == 201
    assert again.get("/api/transactions", params={"month": "2026-11"}).json() == []
    assert len(bob.get("/api/transactions", params={"month": "2026-11"}).json()) == 1  # чужие данные не тронуты


def test_excel_export_and_import_round_trip(make_client):
    import base64

    alice, bob = make_client(), make_client()
    alice.post("/api/auth/register", json={"email": "alice@kz.kz", "password": "password123"})
    bob.post("/api/auth/register", json={"email": "bob@kz.kz", "password": "password123"})
    items = [
        {"date": "2026-10-30", "amount": 1500, "category": "products", "description": "мясо"},
        {"date": "2026-11-10", "amount": 300, "category": "transport", "description": "такси"},
    ]
    alice.post("/api/transactions", json={"items": items})

    month = alice.get("/api/export.xlsx", params={"month": "2026-11"})
    assert month.status_code == 200
    assert month.headers["content-type"].startswith("application/vnd.openxmlformats")
    everything = alice.get("/api/export.xlsx", params={"all": "true"})
    assert 'filename="finance-all.xlsx"' in everything.headers["content-disposition"]

    payload = {"xlsx": base64.b64encode(everything.content).decode()}
    result = bob.post("/api/import", json=payload)
    assert result.status_code == 201, result.text
    assert result.json() == {"imported": 2, "months": ["2026-10", "2026-11"]}
    assert bob.get("/api/transactions", params={"month": "2026-10"}).json()[0]["description"] == "мясо"

    assert bob.post("/api/import", json={"xlsx": "!!!"}).status_code == 422
    assert bob.post("/api/import", json={}).status_code == 422


def test_demo_login_seeds_fresh_data(make_client):
    from datetime import date

    c = make_client()
    r = c.post("/api/auth/demo")
    assert r.status_code == 200 and r.json()["user"]["email"] == "demo@finance.demo"
    month = date.today().strftime("%Y-%m")
    rows = c.get("/api/transactions", params={"month": month}).json()
    assert rows, "в текущем месяце есть записи"
    assert c.get("/api/budgets").json()

    # Посетитель удалил запись — следующий демо-вход вернёт данные как были
    c.delete(f"/api/transactions/{rows[0]['id']}")
    other = make_client()
    other.post("/api/auth/demo")
    assert len(other.get("/api/transactions", params={"month": month}).json()) == len(rows)

    # Демо нельзя удалить или сменить ему пароль
    assert other.request("DELETE", "/api/auth/account", json={"password": "x"}).status_code == 403
    assert other.post("/api/auth/password", json={"current_password": "x", "new_password": "newpass123"}).status_code == 403


def test_demo_seed_without_api():
    import pytest

    pytest.importorskip("sqlalchemy")
    from datetime import date

    from app.demo import _month_rows
    import random

    rows = _month_rows(1, date(2026, 10, 1), date(2026, 10, 31), random.Random(1))
    kinds = {r.kind for r in rows}
    assert {"expense", "income", "lend", "repaid"} <= kinds
    assert all(r.amount > 0 for r in rows)


def test_transcribe_voice(make_client, monkeypatch):
    from app import main
    from app.config import settings
    from app.parser.speech import SpeechError

    c = make_client()
    assert c.post("/api/transcribe", content=b"x", headers={"content-type": "audio/webm"}).status_code == 401
    c.post("/api/auth/register", json={"email": "v@kz.kz", "password": "password123"})

    monkeypatch.setattr(settings, "ai_api_key", None)
    assert c.post("/api/transcribe", content=b"x", headers={"content-type": "audio/webm"}).status_code == 503

    monkeypatch.setattr(settings, "ai_api_key", "key")
    monkeypatch.setattr(settings, "stt_model", "whisper-large-v3")
    seen = {}

    def fake(audio, content_type):
        seen["args"] = (audio, content_type)
        return "такси 1 200, самса 500"

    monkeypatch.setattr(main, "transcribe", fake)
    r = c.post("/api/transcribe", content=b"audio-bytes", headers={"content-type": "audio/webm;codecs=opus"})
    assert r.status_code == 200 and r.json() == {"text": "такси 1 200, самса 500"}
    assert seen["args"] == (b"audio-bytes", "audio/webm;codecs=opus")

    assert c.post("/api/transcribe", content=b"x", headers={"content-type": "text/plain"}).status_code == 415
    assert c.post("/api/transcribe", content=b"", headers={"content-type": "audio/webm"}).status_code == 422
    big = b"0" * (5 * 1024 * 1024 + 1)
    assert c.post("/api/transcribe", content=big, headers={"content-type": "audio/webm"}).status_code == 413

    def broken(audio, content_type):
        raise SpeechError("Не расслышал — попробуйте сказать ещё раз чуть громче")

    monkeypatch.setattr(main, "transcribe", broken)
    r = c.post("/api/transcribe", content=b"x", headers={"content-type": "audio/webm"})
    assert r.status_code == 502 and "Не расслышал" in r.json()["detail"]


def test_delete_debt_removes_all_its_records_only(make_client):
    alice, bob = make_client(), make_client()
    alice.post("/api/auth/register", json={"email": "alice@kz.kz", "password": "password123"})
    bob.post("/api/auth/register", json={"email": "bob@kz.kz", "password": "password123"})
    items = [
        {"date": "2026-10-09", "amount": 15000, "category": "lend", "counterparty": "Айбек"},
        {"date": "2026-11-02", "amount": 5000, "category": "repaid", "counterparty": "айбек "},
        {"date": "2026-11-03", "amount": 3000, "category": "lend", "counterparty": "Дана"},
        {"date": "2026-11-03", "amount": 700, "category": "transport", "description": "такси"},
    ]
    alice.post("/api/transactions", json={"items": items})
    bob.post("/api/transactions", json={"items": [items[0]]})

    r = alice.request("DELETE", "/api/debts", params={"person": "Айбек"})
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert [d["person"] for d in alice.get("/api/debts").json()] == ["Дана"]
    nov = alice.get("/api/transactions", params={"month": "2026-11"}).json()
    assert {t["category"] for t in nov} == {"lend", "transport"}  # такси и Дана на месте
    assert alice.request("DELETE", "/api/debts", params={"person": "Айбек"}).status_code == 404
    assert bob.get("/api/debts").json()[0]["person"] == "Айбек"  # чужой долг не тронут
