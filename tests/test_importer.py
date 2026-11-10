from datetime import date

from app.importer import parse_csv


def test_roundtrip_with_export_format():
    text = "﻿Дата;Тип;Категория;Сумма;Описание\n2026-11-01;Расход;Транспорт и такси;660,00;такси\n"
    items, errors = parse_csv(text)
    assert errors == []
    assert items[0].date == date(2026, 11, 1)
    assert items[0].category == "transport"
    assert items[0].amount == 660


def test_short_dates_keys_spaces_and_commas():
    text = "01.11.26,,income,140 000,от брата\n02.11.2026,,Кафе и перекусы,500,самса"
    items, errors = parse_csv(text)
    assert errors == []
    assert [(i.date.day, i.category, i.kind, i.amount) for i in items] == [
        (1, "income", "income", 140000),
        (2, "cafe", "expense", 500),
    ]


def test_errors_have_line_numbers():
    text = "Дата;Тип;Категория;Сумма\n2026-11-01;;Казино;100\n31.02.2026;;Продукты;100\n2026-11-02;;Продукты;0\n2026-11-03;;Продукты"
    items, errors = parse_csv(text)
    assert items == []
    assert errors[0].startswith("строка 2") and "Казино" in errors[0]
    assert errors[1].startswith("строка 3")
    assert errors[2].startswith("строка 4")
    assert errors[3].startswith("строка 5")
