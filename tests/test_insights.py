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
    assert "Алижан" not in text or len(points) <= 4
    assert len(points) <= 4


def test_empty_month():
    assert rule_insights(build_facts(make_summary(by_category=[], expense=0), [])) == ["В ноябре расходов пока нет."]
