from datetime import date

from app.personalize import apply_examples, build_examples, normalize
from app.schemas import ParsedItem


def test_normalize_keeps_meaningful_words():
    assert normalize("Сегодня купил Самсу за 500") == "самсу"
    assert normalize("такси до универа") == "такси до универа"


def test_newest_record_wins_and_debts_are_ignored():
    rows = [  # от новых к старым
        ("самсу", "cafe"),  # исправление
        ("самсу", "products"),
        ("Алижан", "lend"),
        ("хлеб", "products"),
    ]
    assert build_examples(rows) == {"самсу": "cafe", "хлеб": "products"}


def test_apply_examples_changes_category_and_kind():
    items = [
        ParsedItem(date=date(2026, 11, 12), amount=500, category="products", description="съел самсу"),
        ParsedItem(date=date(2026, 11, 12), amount=300, category="transport", description="такси"),
    ]
    result, changed = apply_examples(items, {"самсу": "cafe"})
    assert changed == 1
    assert result[0].category == "cafe" and result[0].kind == "expense"
    assert result[1].category == "transport"


def test_examples_go_to_ai_prompt():
    from app.parser.ai import build_user_message

    message = build_user_message("самса 500", {"самсу": "cafe"})
    assert "самсу -> cafe" in message and message.endswith("самса 500")
    assert build_user_message("самса 500", {}) == "самса 500"


def test_parse_uses_examples_without_ai():
    from app.parser import parse

    # по умолчанию самса — «Кафе и перекусы», но этот пользователь относит её к продуктам
    result = parse("съел самсу 500", date(2026, 11, 12), {"самсу": "products"})
    assert result.items[0].category == "products" and result.learned == 1
