from datetime import date

from app.config import settings
from app.parser.ai import AIParseError, parse_with_ai
from app.parser.rules import parse_text
from app.personalize import apply_examples
from app.schemas import ParseResponse


def parse(text: str, today: date | None = None, examples: dict[str, str] | None = None) -> ParseResponse:
    """Сначала пробуем ИИ, при ошибке или без ключа — простой парсер.

    examples — привычки пользователя «описание -> категория» (см. app/personalize.py).
    """
    examples = examples or {}
    warning = None
    if settings.ai_enabled:
        try:
            items = parse_with_ai(text, today, examples)
            if items:
                items, learned = apply_examples(items, examples)
                return ParseResponse(source="ai", items=items, learned=learned)
            warning = "ИИ не нашёл сумм в тексте, попробовал простой разбор"
        except AIParseError as exc:
            warning = f"{exc}. Использован простой разбор"

    items, unparsed = parse_text(text, today)
    items, learned = apply_examples(items, examples)
    return ParseResponse(source="rules", items=items, unparsed=unparsed, warning=warning, learned=learned)
