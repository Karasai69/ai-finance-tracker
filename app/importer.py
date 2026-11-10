"""Импорт записей из CSV — в том же формате, что и выгрузка «Скачать CSV».

Формат: Дата;Тип;Категория;Сумма;Описание
- Дата: 2026-11-01, 01.11.2026 или 01.11.26
- Тип: необязателен, тип всегда определяется по категории
- Категория: название («Транспорт и такси») или ключ («transport»)
- Сумма: 1 234,50 или 1234.50
"""

import csv
import io
from datetime import date, datetime

from pydantic import ValidationError

from app.categories import CATEGORIES
from app.schemas import ParsedItem

MAX_ROWS = 5000
_NAME_TO_KEY = {name.lower(): key for key, (name, _) in CATEGORIES.items()}


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не понял дату «{value}»")


def _parse_category(value: str) -> str:
    value = value.strip()
    if value in CATEGORIES:
        return value
    key = _NAME_TO_KEY.get(value.lower())
    if key is None:
        raise ValueError(f"неизвестная категория «{value}»")
    return key


def parse_csv(text: str) -> tuple[list[ParsedItem], list[str]]:
    """Возвращает (записи, ошибки). Ошибка — строка вида «строка 5: ...»."""
    text = text.lstrip("﻿")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if ";" in first_line else ","

    items: list[ParsedItem] = []
    errors: list[str] = []
    for line_no, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if line_no == 1 and row[0].strip().lower() in ("дата", "date"):
            continue  # заголовок
        if len(items) + len(errors) >= MAX_ROWS:
            errors.append(f"больше {MAX_ROWS} строк, разбейте файл на части")
            break
        if len(row) < 4:
            errors.append(f"строка {line_no}: нужно минимум 4 колонки (дата, тип, категория, сумма)")
            continue
        try:
            items.append(
                ParsedItem(
                    date=_parse_date(row[0]),
                    category=_parse_category(row[2]),
                    amount=row[3],
                    description=row[4].strip() if len(row) > 4 else "",
                )
            )
        except ValueError as exc:  # ValidationError тоже наследует ValueError
            message = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            errors.append(f"строка {line_no}: {message}")
    return items, errors
