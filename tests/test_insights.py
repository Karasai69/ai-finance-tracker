from app.insights import build_facts, rule_insights
from app.schemas import CategoryTotal, Debt, Summary


def make_summary(**overrides):
    data = dict(
        month="2026-11", income=157500, expense=42000, lent=23000, repaid=0, balance=92500,
        by_category=[
            CategoryTotal(category="sport", name="Спорт", kind="expense", total=22000, prev_total=0),
            CategoryTotal(category="transport", name="Транспорт и такси", kind="expense", total=9000,
                          limit=8000, prev_total=4000),
            CategoryTotal(category="income", name="Доход", kind="income", total=157500),
        ],
        by_day=[], prev_month="2026-10", compare_days=12, expense_to_date=31000, prev_expense=25000,
    )
    data.update(overrides)
    return Summary(**data)


DEBTS = [Debt(person="Алижан", lent=22000, repaid=0, balance=22000, since="2026-11-09", last="2026-11-09")]


def test_facts_have_only_expense_categories():
    facts = build_facts(make_summary(), DEBTS)
    assert [c["название"] for c in facts["категории"]] == ["Спорт", "Транспорт и такси"]
    assert facts["прошлый_месяц"] == "октябре" and facts["мне_должны"] == 22000


def test_rule_insights():
    points = rule_insights(build_facts(make_summary(), DEBTS))
    text = " ".join(points)
    assert "«Спорт»" in text and "52%" in text
    assert "превышен на 1 000 ₸" in text
    assert "на 24% больше" in text
    assert "В среднем вы тратили 3 500 ₸ в день" in text  # 42 000 за 12 дней
    assert "Из доходов осталось 73%" in text
    assert len(points) <= 7


def test_empty_month():
    assert rule_insights(build_facts(make_summary(by_category=[], expense=0), [])) == ["В ноябре расходов пока нет."]


def test_ai_payload_hides_missing_data_and_formats_money():
    from app.insights import ai_payload

    facts = build_facts(make_summary(prev_expense=0), DEBTS, {"sport": 1, "transport": 12})
    payload = ai_payload(facts)
    assert "сравнение_с_прошлым_месяцем" not in payload  # прошлый месяц пустой
    assert payload["категории_расходов"][0]["сумма"] == "22 000 ₸"
    assert payload["лимиты"][0]["превышен"] is True
    # спорт не предлагаем сокращать, такси — частая трата
    assert [c["название"] for c in payload["где_можно_советовать_экономию"]] == ["Транспорт и такси"]


def test_ai_payload_without_limits():
    from app.insights import ai_payload

    summary = make_summary()
    for c in summary.by_category:
        c.limit = None
    assert "лимиты" not in ai_payload(build_facts(summary, []))


def test_big_purchases_in_facts_and_payload():
    from app.insights import ai_payload

    big = [{"описание": "кроссовки", "категория": "Одежда", "сумма": 30000.4, "дата": "05.11"}]
    facts = build_facts(make_summary(), DEBTS, big=big)
    assert facts["крупные_покупки"][0]["сумма"] == 30000
    assert "«кроссовки», 30 000 ₸ (05.11)" in " ".join(rule_insights(facts))
    payload = ai_payload(facts)
    assert payload["крупные_покупки"][0]["сумма"] == "30 000 ₸"
    assert payload["остаток_от_доходов"]["процент_от_доходов"] == "73%"
    assert payload["сильнее_всего_изменились"][0]["название"] == "Спорт"
