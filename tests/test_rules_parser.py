from datetime import date

from app.parser.rules import parse_text

TODAY = date(2026, 11, 10)


def parse(text):
    items, unparsed = parse_text(text, TODAY)
    return [(i.category, i.amount, i.kind) for i in items], unparsed


def test_several_items_with_commas():
    items, _ = parse("такси 300, овощи 896, продукты 2830")
    assert items == [
        ("transport", 300, "expense"),
        ("vegetables", 896, "expense"),
        ("products", 2830, "expense"),
    ]


def test_items_without_commas():
    items, _ = parse("такси 300 овощи 896")
    assert [(c, a) for c, a, _ in items] == [("transport", 300), ("vegetables", 896)]


def test_thousands_with_space_and_k_suffix():
    items, _ = parse("брат прислал 10 000\nзарплата 150к")
    assert items == [("income", 10000, "income"), ("income", 150000, "income")]


def test_income_from_someone():
    items, _ = parse("10000 от брата")
    assert items == [("income", 10000, "income")]


def test_lend_money():
    items, _ = parse("дал Султану в долг 22000")
    assert items == [("lend", 22000, "lend")]


def test_decimal_and_currency():
    items, _ = parse("магазин 420,50 тг")
    assert items == [("convenience", 420.5, "expense")]


def test_unknown_goes_to_other_and_text_without_number_is_reported():
    items, unparsed = parse("что-то купил 500, просто заметка")
    assert items == [("other", 500, "expense")]
    assert unparsed == ["просто заметка"]


def test_description_is_cleaned():
    items, _ = parse_text("такси до универа 300 тг", TODAY)
    assert items[0].description == "такси до универа"
    assert items[0].date == TODAY


def test_food_and_clean_description():
    items, _ = parse_text("сегодня съел самсу за 500 и мороженое за 500", TODAY)
    assert [(i.category, i.amount, i.description) for i in items] == [
        ("cafe", 500, "съел самсу"),
        ("cafe", 500, "мороженое"),
    ]


def test_instant_noodles_is_cafe():
    items, _ = parse("дошик 300")
    assert items == [("cafe", 300, "expense")]


def test_lend_and_repaid_get_person():
    items, _ = parse_text("дал Султану в долг 10000, Алижан вернул 5000", TODAY)
    assert [(i.category, i.amount, i.counterparty) for i in items] == [
        ("lend", 10000, "Султан"),
        ("repaid", 5000, "Алижан"),
    ]
