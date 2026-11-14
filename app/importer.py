"""Импорт записей из Excel (.xlsx) или CSV — в том же формате, что и выгрузка.

Колонки: Дата | Тип | Категория | Сумма | Описание | Кто (необязательно)
- Дата: 2026-11-01, 01.11.2026 или 01.11.26
- Тип: необязателен, тип всегда определяется по категории
- Категория: название («Транспорт и такси») или ключ («transport»)
- Сумма: 1 234,50 или 1234.50
"""

import csv
import io
from datetime import date, datetime
from typing import Any, Iterable

from pydantic import ValidationError

from app.categories import CATEGORIES
from app.schemas import ParsedItem

MAX_ROWS = 5000
_NAME_TO_KEY = {name.lower(): key for key, (name, _) in CATEGORIES.items()}


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не понял дату «{value}»")


def _parse_category(value: Any) -> str:
    value = str(value or "").strip()
    if value in CATEGORIES:
        return value
    key = _NAME_TO_KEY.get(value.lower())
    if key is None:
        raise ValueError(f"неизвестная категория «{value}»")
    return key


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _amount(value: Any) -> Any:
    # Число из Excel берём как есть, текст разбирает схема («1 234,50»)
    return value if isinstance(value, (int, float)) else _text(value)


def parse_rows(rows: Iterable[list[Any]]) -> tuple[list[ParsedItem], list[str]]:
    """Общий разбор строк таблицы. Возвращает (записи, ошибки) — ошибка вида «строка 5: ...»."""
    items: list[ParsedItem] = []
    errors: list[str] = []
    for line_no, row in enumerate(rows, start=1):
        row = list(row)
        if not row or all(_text(cell) == "" for cell in row):
            continue
        if line_no == 1 and _text(row[0]).lower() in ("дата", "date"):
            continue  # заголовок
        if len(items) + len(errors) >= MAX_ROWS:
            errors.append(f"больше {MAX_ROWS} строк, разбейте файл на части")
            break
        if len(row) < 4 or _text(row[3]) == "":
            errors.append(f"строка {line_no}: нужно минимум 4 колонки (дата, тип, категория, сумма)")
            continue
        try:
            items.append(
                ParsedItem(
                    date=_parse_date(row[0]),
                    category=_parse_category(row[2]),
                    amount=_amount(row[3]),
                    description=_text(row[4]) if len(row) > 4 else "",
                    counterparty=(_text(row[5]) or None) if len(row) > 5 else None,
                )
            )
        except ValueError as exc:  # ValidationError тоже наследует ValueError
            message = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            errors.append(f"строка {line_no}: {message}")
    return items, errors


def parse_csv(text: str) -> tuple[list[ParsedItem], list[str]]:
    text = text.lstrip("\ufeff")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if ";" in first_line else ","
    return parse_rows(csv.reader(io.StringIO(text), delimiter=delimiter))


def parse_xlsx(data: bytes) -> tuple[list[ParsedItem], list[str]]:
    """Читает лист «Записи» (или первый лист) файла Excel."""
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return [], ["не получилось открыть файл: нужен Excel .xlsx"]
    sheet = book["Записи"] if "Записи" in book.sheetnames else book.worksheets[0]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    book.close()
    return parse_rows(rows)
