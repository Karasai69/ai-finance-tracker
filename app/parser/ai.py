"""Разбор текста с помощью языковой модели.

Модель получает свободный текст («вчера такси 300, овощи 896, брат прислал 10к»)
и возвращает JSON со списком записей. Ответ модели всегда проверяется через Pydantic:
неизвестная категория превращается в «Другое», запись без суммы отбрасывается.
"""

import json
import re
from datetime import date, timedelta

from pydantic import ValidationError

from app.categories import CATEGORIES, CATEGORY_HINTS
from app.config import settings
from app.schemas import ParsedItem


class AIParseError(Exception):
    pass


def build_system_prompt(today: date) -> str:
    categories = "\n".join(
        f'- "{key}": {name} — {CATEGORY_HINTS.get(key, name)}' for key, (name, kind) in CATEGORIES.items()
    )
    return f"""Ты помощник для учёта личных финансов. Пользователь пишет, на что потратил
или сколько получил денег, на русском, казахском или английском. Валюта по умолчанию — тенге.

Сегодня {today.isoformat()} ({today.strftime('%A')}). «Вчера» = {(today - timedelta(days=1)).isoformat()}.

Разбей текст на отдельные операции и верни ТОЛЬКО JSON вида:
{{"items": [{{"date": "YYYY-MM-DD", "amount": 300, "category": "transport", "description": "такси"}}]}}

Правила:
- category — строго один из ключей:
{categories}
- Готовую еду и перекусы (самса, шаурма, мороженое, доширак, кофе) относи к "cafe",
  а продукты для готовки дома — к "products".
- Деньги, которые пользователь получил (зарплата, перевод от родственника), — "income".
- Деньги, которые пользователь дал кому-то в долг, — "lend"; имя человека оставь в description.
- amount — положительное число без валюты. «10к» = 10000.
- description — коротко, 1–5 слов, на языке пользователя.
- Если дата не указана, используй сегодняшнюю.
- Если в тексте нет ни одной суммы, верни {{"items": []}}.
"""


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    # Модели иногда оборачивают JSON в ```json ... ```
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise AIParseError("Модель вернула ответ без JSON")
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIParseError(f"Некорректный JSON от модели: {exc}") from exc


def items_from_ai_response(raw: str, today: date) -> list[ParsedItem]:
    data = _extract_json(raw)
    items = []
    for entry in data.get("items", []):
        if not isinstance(entry, dict):
            continue
        entry = {**entry}
        entry.setdefault("date", today.isoformat())
        try:
            items.append(ParsedItem(**entry))
        except ValidationError:
            continue  # пропускаем запись без суммы или с битой датой
    return items


def parse_with_ai(text: str, today: date | None = None) -> list[ParsedItem]:
    today = today or date.today()
    if not settings.ai_enabled:
        raise AIParseError("ИИ не настроен: задайте AI_API_KEY и AI_MODEL в .env")

    from openai import OpenAI  # импорт здесь, чтобы тесты работали без пакета

    client = OpenAI(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        timeout=settings.ai_timeout,
    )
    try:
        response = client.chat.completions.create(
            model=settings.ai_model,
            messages=[
                {"role": "system", "content": build_system_prompt(today)},
                {"role": "user", "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # сеть, лимиты, неверный ключ
        status = getattr(exc, "status_code", None)
        if status == 404:
            raise AIParseError(f"Модель «{settings.ai_model}» не найдена у провайдера, проверьте AI_MODEL в .env") from exc
        if status == 401:
            raise AIParseError("Неверный ключ ИИ, проверьте AI_API_KEY в .env") from exc
        if status == 429:
            raise AIParseError("Превышен лимит запросов к ИИ, попробуйте через минуту") from exc
        raise AIParseError(f"Ошибка запроса к ИИ: {exc}") from exc

    content = response.choices[0].message.content or ""
    return items_from_ai_response(content, today)
