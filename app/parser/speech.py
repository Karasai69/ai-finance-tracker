"""Распознавание речи на сервере: Whisper через OpenAI-совместимый API (Groq или OpenAI).

Встроенное распознавание браузера часто путает суммы, имена и казахские слова.
Whisper заметно точнее, а подсказка (prompt) задаёт ему стиль: суммы цифрами,
местные названия магазинов и слова, которые часто звучат в тратах.
"""

from openai import APIStatusError, OpenAI, OpenAIError

from app.config import settings

# Подсказка Whisper: как писать суммы и какие слова встречаются (до 224 токенов)
PROMPT = (
    "Траты и доходы за день. Суммы цифрами в тенге: такси 1 200, самса 500, обед 1 500, "
    "Magnum 8 400, Kaspi, Small, кофе 900, брат прислал 10 000, дал в долг Алижану 5 000, "
    "вернул долг, садака 500, стипендия, зарплата."
)

MAX_BYTES = 5 * 1024 * 1024  # около 5 минут речи в webm/opus — с большим запасом
EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
              "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "m4a"}


class SpeechError(Exception):
    pass


def extension_for(content_type: str) -> str:
    return EXTENSIONS.get((content_type or "").split(";")[0].strip().lower(), "webm")


def transcribe(audio: bytes, content_type: str) -> str:
    """Аудио → текст. Бросает SpeechError с понятным сообщением."""
    client = OpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url, timeout=settings.ai_timeout)
    try:
        result = client.audio.transcriptions.create(
            model=settings.stt_model,
            file=(f"voice.{extension_for(content_type)}", audio, content_type or "audio/webm"),
            language="ru",
            prompt=PROMPT,
            temperature=0,
        )
    except APIStatusError as exc:
        if exc.status_code == 429:
            raise SpeechError("Распознавание временно перегружено, попробуйте через минуту") from exc
        raise SpeechError(f"Сервис распознавания ответил ошибкой {exc.status_code}") from exc
    except OpenAIError as exc:
        raise SpeechError("Не получилось связаться с сервисом распознавания") from exc
    text = (getattr(result, "text", "") or "").strip()
    # Whisper на тишине иногда «досочиняет» подсказку — такой текст отбрасываем
    if not text or text in PROMPT:
        raise SpeechError("Не расслышал — попробуйте сказать ещё раз чуть громче")
    return text
