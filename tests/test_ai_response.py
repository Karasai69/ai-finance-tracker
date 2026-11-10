"""Проверяем разбор ответа модели без настоящего запроса к ИИ."""

from datetime import date

import pytest

from app.parser.ai import AIParseError, build_system_prompt, items_from_ai_response

TODAY = date(2026, 11, 10)


def test_valid_json():
    raw = '{"items": [{"date": "2026-11-09", "amount": 300, "category": "transport", "description": "такси"}]}'
    items = items_from_ai_response(raw, TODAY)
    assert len(items) == 1
    assert items[0].date == date(2026, 11, 9)
    assert items[0].kind == "expense"


def test_json_in_code_fence_and_missing_date():
    raw = '```json\n{"items": [{"amount": "10 000", "category": "income", "description": "от брата"}]}\n```'
    items = items_from_ai_response(raw, TODAY)
    assert items[0].amount == 10000
    assert items[0].date == TODAY
    assert items[0].kind == "income"


def test_unknown_category_becomes_other_and_bad_items_are_skipped():
    raw = """{"items": [
        {"amount": 500, "category": "casino", "description": "?"},
        {"amount": -5, "category": "products"},
        {"category": "products"},
        "мусор"
    ]}"""
    items = items_from_ai_response(raw, TODAY)
    assert [(i.category, i.amount) for i in items] == [("other", 500)]


def test_kind_always_follows_category():
    raw = '{"items": [{"amount": 100, "category": "lend", "kind": "expense"}]}'
    assert items_from_ai_response(raw, TODAY)[0].kind == "lend"


def test_not_json_raises():
    with pytest.raises(AIParseError):
        items_from_ai_response("Извините, не понял", TODAY)


def test_prompt_lists_all_categories_and_dates():
    prompt = build_system_prompt(TODAY)
    assert '"transport"' in prompt and '"lend"' in prompt
    assert "2026-11-10" in prompt and "2026-11-09" in prompt


def test_prompt_explains_cafe_vs_products():
    prompt = build_system_prompt(TODAY)
    assert "самса" in prompt and '"cafe"' in prompt
