from datetime import date

from app.config import settings
from app.parser.ai import AIParseError, parse_with_ai
from app.parser.rules import parse_text
from app.schemas import ParseResponse


def parse(text: str, today: date | None = None) -> ParseResponse:
    """Сначала пробуем ИИ, при ошибке или без ключа — простой парсер."""
    warning = None
    if settings.ai_enabled:
        try:
            items = parse_with_ai(text, today)
            if items:
                return ParseResponse(source="ai", items=items)
            warning = "ИИ не нашёл сумм в тексте, попробовал простой разбор"
        except AIParseError as exc:
            warning = f"{exc}. Использован простой разбор"

    items, unparsed = parse_text(text, today)
    return ParseResponse(source="rules", items=items, unparsed=unparsed, warning=warning)
