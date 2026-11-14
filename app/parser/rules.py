"""Запасной парсер без ИИ.

Работает, когда ключ к ИИ не задан или ИИ недоступен.
Понимает простые записи: «такси 300, овощи 896», «10к от брата», «дал Султану в долг 10 000».
"""

import re
from datetime import date

from app.categories import DEFAULT_CATEGORY, KEYWORDS, PERSON_KINDS, kind_of
from app.schemas import ParsedItem

# 10 000 | 10000 | 420,50 | 1.5 ; затем необязательный множитель: к, k, тыс
NUMBER_RE = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(тыс\.?|к|k)?(?![\w])",
    re.IGNORECASE,
)
CHUNK_SPLIT_RE = re.compile(r"[;\n]+|,(?!\d)")
WORD_RE = re.compile(r"[\w%]+", re.UNICODE)


def _to_amount(number: str, multiplier: str | None) -> float:
    value = float(number.replace(" ", "").replace(" ", "").replace(",", "."))
    if multiplier:
        value *= 1000
    return round(value, 2)


def guess_category(text: str) -> str:
    words = [w.lower() for w in WORD_RE.findall(text)]
    if words and words[0] == "от":
        return "income"  # «10000 от брата»
    joined = " ".join(words)
    for category, keys in KEYWORDS.items():
        # Ключи из нескольких слов («из копилк») ищем во всей фразе, остальные — по началу слова
        if any(" " in key and key in joined for key in keys):
            return category
        for word in words:
            if any(" " not in key and word.startswith(key) for key in keys):
                return category
    return DEFAULT_CATEGORY


# Слова, которые не несут смысла в начале или в конце описания:
# «сегодня съел самсу за 500» -> «съел самсу»
LEADING_WORDS = {"сегодня", "вчера", "и", "а", "ещё", "еще", "также", "потом", "плюс"}
TRAILING_WORDS = {"за", "на", "по", "и", "в", "тг", "тенге", "kzt"}


def _clean_description(text: str) -> str:
    text = NUMBER_RE.sub(" ", text).replace("₸", " ")
    words = text.split()
    while words and words[0].lower().strip(".,:") in LEADING_WORDS:
        words.pop(0)
    while words and words[-1].lower().strip(".,:") in TRAILING_WORDS:
        words.pop()
    return " ".join(words).strip(" -—:.")


def guess_person(text: str) -> str | None:
    """Имя человека — первое слово с заглавной буквы: «дал Султану в долг» -> «Султан».

    Простое правило для дательного падежа: «Султану», «Мадияру» -> без последней «у/ю».
    ИИ справляется с именами точнее, это запасной вариант.
    """
    for word in WORD_RE.findall(text):
        if word[:1].isupper() and word[:1].isalpha():
            if len(word) > 4 and word[-1] in "уюУЮ":
                word = word[:-1]
            return word
    return None


def parse_text(text: str, today: date | None = None) -> tuple[list[ParsedItem], list[str]]:
    """Возвращает (распознанные записи, куски текста без суммы)."""
    today = today or date.today()
    items: list[ParsedItem] = []
    unparsed: list[str] = []

    for chunk in CHUNK_SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        matches = list(NUMBER_RE.finditer(chunk))
        if not matches:
            unparsed.append(chunk)
            continue

        # «такси 300 овощи 896» -> «такси 300» и «овощи 896»;
        # слова после последней суммы относятся к последней записи («10000 от брата»).
        start = 0
        for i, match in enumerate(matches):
            end = len(chunk) if i == len(matches) - 1 else match.end()
            piece = chunk[start:end]
            start = end

            amount = _to_amount(match.group(1), match.group(2))
            if amount <= 0:
                continue
            description = _clean_description(piece) or chunk
            category = guess_category(description)
            kind = kind_of(category)
            items.append(
                ParsedItem(
                    date=today,
                    amount=amount,
                    category=category,
                    kind=kind,
                    description=description,
                    counterparty=guess_person(piece) if kind in PERSON_KINDS else None,
                )
            )
    return items, unparsed
