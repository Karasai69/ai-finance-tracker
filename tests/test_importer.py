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


# ---------- Excel ----------

def test_excel_round_trip():
    """Выгрузка в Excel читается обратно без потерь — лист «Записи»."""
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from app.excel import build_workbook
    from app.importer import parse_xlsx

    rows = [
        SimpleNamespace(date=date(2026, 11, 9), kind="lend", category="lend", amount=Decimal("22000"),
                        description="", counterparty="Алижан"),
        SimpleNamespace(date=date(2026, 11, 9), kind="expense", category="sport", amount=Decimal("22000"),
                        description="борьба", counterparty=None),
        SimpleNamespace(date=date(2026, 11, 10), kind="expense", category="transport", amount=Decimal("300.50"),
                        description="такси", counterparty=None),
        SimpleNamespace(date=date(2026, 11, 10), kind="income", category="income", amount=Decimal("10000"),
                        description="от брата", counterparty=None),
    ]
    data = build_workbook(rows, "тест")
    items, errors = parse_xlsx(data)
    assert errors == []
    assert [(i.date, i.category, float(i.amount)) for i in items] == [
        (date(2026, 11, 9), "lend", 22000), (date(2026, 11, 9), "sport", 22000),
        (date(2026, 11, 10), "transport", 300.5), (date(2026, 11, 10), "income", 10000),
    ]
    assert items[0].counterparty == "Алижан" and items[2].description == "такси"

    from openpyxl import load_workbook
    import io

    book = load_workbook(io.BytesIO(data))
    assert book.sheetnames == ["Записи", "По дням"]
    days = book["По дням"]
    header = [c.value for c in days[1]]
    assert header[:5] == ["Дата", "День", "Расходы за день", "Доход", "Дал в долг"]
    assert days.cell(row=2, column=3).value == 22000  # расходы 9 ноября: долг не расход
    assert str(days.cell(row=days.max_row, column=1).value) == "Итого"


def test_excel_errors_and_broken_file():
    import io

    from openpyxl import Workbook

    from app.importer import parse_xlsx

    book = Workbook()
    sheet = book.active
    sheet.append(["Дата", "Тип", "Категория", "Сумма"])
    sheet.append(["01.11.2026", "", "Транспорт и такси", "300"])  # даты и суммы текстом — тоже понимаем
    sheet.append(["01.11.2026", "", "Космос", 100])
    buffer = io.BytesIO()
    book.save(buffer)
    items, errors = parse_xlsx(buffer.getvalue())
    assert len(items) == 1 and items[0].category == "transport"
    assert errors == ["строка 3: неизвестная категория «Космос»"]

    assert parse_xlsx(b"not an excel file") == ([], ["не получилось открыть файл: нужен Excel .xlsx"])


def test_old_ten_percent_rows_become_savings():
    items, errors = parse_csv("01.11.2026;;10 процентов;17 250;\n02.11.2026;;ten_percent;5000;")
    assert errors == []
    assert [(i.category, i.kind) for i in items] == [("savings", "save"), ("savings", "save")]
