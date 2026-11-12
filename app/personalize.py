"""Как ИИ «учится» на исправлениях пользователя.

Модель не дообучается. Вместо этого из истории пользователя собирается словарь
«описание -> категория»: если пользователь однажды переложил «самсу» из «Продуктов»
в «Кафе и перекусы», последняя (исправленная) запись побеждает. Словарь:
1) передаётся ИИ как подсказка — так он обобщает и на похожие траты;
2) применяется к готовому результату — так исправление гарантированно повторится.
"""

import re
from collections.abc import Iterable

from app.categories import PERSON_KINDS, kind_of
from app.schemas import ParsedItem

# Слова, которые не говорят о том, что именно куплено
STOP_WORDS = {
    "сегодня", "вчера", "позавчера", "купил", "купила", "взял", "взяла", "съел", "съела", "выпил",
    "заплатил", "заплатила", "потратил", "потратила", "оплатил", "оплатила", "за", "на", "и", "в", "с",
    "тг", "тенге", "кзт",
}
MAX_EXAMPLES = 40


def normalize(text: str) -> str:
    """«Сегодня купил Самсу за 500» -> «самсу»: только смысловые слова, максимум три."""
    words = [w for w in re.findall(r"[^\W\d_]+", text.lower()) if w not in STOP_WORDS]
    return " ".join(words[:3])


def build_examples(rows: Iterable[tuple[str, str]], limit: int = MAX_EXAMPLES) -> dict[str, str]:
    """rows — пары (описание, категория) от новых к старым. Новая запись побеждает старую."""
    examples: dict[str, str] = {}
    for description, category in rows:
        if kind_of(category) in PERSON_KINDS:
            continue  # у долгов в описании имена людей, это не привычки
        key = normalize(description or "")
        if key and key not in examples:
            examples[key] = category
            if len(examples) >= limit:
                break
    return examples


def apply_examples(items: list[ParsedItem], examples: dict[str, str]) -> tuple[list[ParsedItem], int]:
    """Подставляет категорию из привычек пользователя. Возвращает (записи, сколько исправлено)."""
    if not examples:
        return items, 0
    result, changed = [], 0
    for item in items:
        category = examples.get(normalize(item.description))
        if category and category != item.category and item.kind not in PERSON_KINDS:
            item = ParsedItem(**{**item.model_dump(), "category": category})
            changed += 1
        result.append(item)
    return result, changed
