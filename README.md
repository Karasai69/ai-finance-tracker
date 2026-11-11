# AI Finance Tracker

[![tests](https://github.com/Karasai69/ai-finance-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/Karasai69/ai-finance-tracker/actions/workflows/tests.yml)

Веб-приложение для учёта личных финансов. Пишете или говорите обычным текстом:

> такси 300, овощи 896, брат прислал 10000, дал Султану в долг 5000

ИИ раскладывает текст на записи с категориями и суммами. Вы проверяете их и сохраняете, а приложение собирает таблицу по дням и категориям, считает итоги месяца и выгружает данные в CSV.

Проект вырос из таблицы в Google Sheets, которую я каждый день заполнял вручную.

**Демо:** https://ai-finance-tracker-05rj.onrender.com — зарегистрируйтесь и попробуйте написать «вчера на такси ушло 300».

> Сервер на бесплатном тарифе Render засыпает без посетителей, поэтому первое открытие может занять до минуты.

## Возможности

- Регистрация и вход, у каждого пользователя свои данные
- Ввод свободным текстом или голосом (Chrome, Edge, Safari)
- Разбор текста языковой моделью: категории, суммы, даты («вчера»), доходы и долги
- Запасной разбор по ключевым словам, если ИИ недоступен
- Предпросмотр: перед сохранением можно поправить категорию, сумму и дату
- Таблица «дни × категории», как в Google Sheets, и список записей
- Итоги месяца: доходы, расходы, деньги в долг, остаток, доли категорий
- Выгрузка месяца в CSV для Excel и Google Sheets
- Страница адаптирована под телефон

## Стек

| Часть | Технологии |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic |
| База данных | PostgreSQL (в продакшене и CI), SQLite (локально) |
| Авторизация | JWT в httpOnly cookie, хеширование паролей scrypt |
| ИИ | LLM через OpenAI-совместимый API (Groq, Gemini, OpenAI) |
| Frontend | HTML, CSS, JavaScript, Web Speech API |
| Инфраструктура | Docker, Docker Compose, GitHub Actions, Render, Neon |
| Тесты | pytest: разбор текста, ответы ИИ, авторизация, изоляция данных пользователей |

## Как это устроено

1. Пользователь пишет текст, фронтенд отправляет его на `POST /api/parse`.
2. Backend просит модель вернуть JSON со списком операций. Ответ проверяется через Pydantic: неизвестная категория становится «Другое», запись без суммы отбрасывается, тип операции всегда следует из категории.
3. Если ИИ не настроен или не ответил, срабатывает простой парсер на регулярных выражениях.
4. Пользователь правит предпросмотр и сохраняет записи в базу (`POST /api/transactions`).
5. Итоги считаются SQL-запросами с `GROUP BY`, все запросы ограничены записями текущего пользователя.

## Запуск на компьютере

Нужен Python 3.10 или новее.

```bash
git clone https://github.com/Karasai69/ai-finance-tracker.git
cd ai-finance-tracker

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements-dev.txt
copy .env.example .env          # Windows; на macOS / Linux: cp .env.example .env

uvicorn app.main:app --reload
```

Откройте http://127.0.0.1:8000 и зарегистрируйтесь. Документация API: http://127.0.0.1:8000/docs.

### Подключение ИИ (бесплатно, Groq)

1. Зарегистрируйтесь на https://console.groq.com и создайте ключ в разделе **API Keys**.
2. Вставьте его в `.env`:
   ```
   AI_API_KEY=ваш_ключ
   AI_BASE_URL=https://api.groq.com/openai/v1
   AI_MODEL=openai/gpt-oss-20b
   ```
   Актуальный список моделей: https://console.groq.com/docs/models
3. Перезапустите сервер. Под полем ввода появится надпись «Текст разбирает ИИ».

Подойдёт и другой провайдер с OpenAI-совместимым API: поменяйте `AI_BASE_URL` и `AI_MODEL`.

### Запуск в Docker вместе с PostgreSQL

```bash
docker compose up --build
```

Приложение откроется на http://127.0.0.1:8000, данные хранятся в PostgreSQL.

## Деплой: Render + Neon (бесплатно)

1. **База.** Создайте проект на https://neon.com и скопируйте строку подключения (Connection string) вида `postgresql://...`.
2. **Сервер.** На https://render.com: **New → Blueprint**, выберите этот репозиторий. Render прочитает `render.yaml`.
3. Заполните переменные: `DATABASE_URL` — строка из Neon, `AI_API_KEY` — ключ Groq, `AI_MODEL` — название модели. `SECRET_KEY` Render сгенерирует сам.
4. После сборки сайт будет доступен по адресу вида `https://ai-finance-tracker.onrender.com`.

На бесплатном тарифе Render сервер засыпает после 15 минут без запросов, поэтому первое открытие может занять около минуты.

## Тесты

```bash
pytest
```

GitHub Actions запускает тесты на каждый push дважды: на SQLite и на PostgreSQL. Отдельно проверяется, что собирается Docker-образ.

## Структура

```
app/
  main.py          # FastAPI: маршруты API и отдача страницы
  auth.py          # регистрация, вход, проверка пользователя
  security.py      # хеширование паролей и JWT
  models.py        # таблицы users и transactions (SQLAlchemy)
  schemas.py       # проверка данных (Pydantic)
  categories.py    # категории и ключевые слова
  parser/
    ai.py          # разбор текста языковой моделью
    rules.py       # запасной разбор без ИИ
  static/          # веб-страница: index.html, style.css, app.js
tests/             # pytest
Dockerfile, docker-compose.yml, render.yaml
.github/workflows/tests.yml
```

## API

Все маршруты, кроме входа, регистрации, `/api/health` и `/api/categories`, требуют входа в аккаунт.

| Метод | Путь | Что делает |
| --- | --- | --- |
| POST | `/api/auth/register` | Регистрация |
| POST | `/api/auth/login` | Вход |
| POST | `/api/auth/logout` | Выход |
| GET | `/api/auth/me` | Текущий пользователь |
| POST | `/api/parse` | Текст → список записей (без сохранения) |
| POST | `/api/transactions` | Сохранить записи |
| GET | `/api/transactions?month=2026-11` | Записи за месяц |
| PATCH | `/api/transactions/{id}` | Изменить запись |
| DELETE | `/api/transactions/{id}` | Удалить запись |
| GET | `/api/summary?month=2026-11` | Итоги месяца |
| GET | `/api/export.csv?month=2026-11` | Выгрузка в CSV |
| GET | `/api/categories` | Список категорий |
| GET | `/api/health` | Проверка сервера и статус ИИ |

## Планы

- [ ] Учёт долгов: кто вернул, сколько осталось
- [ ] Лимиты по категориям
- [ ] Сравнение с прошлым месяцем, график по дням
- [ ] Установка на телефон (PWA)
- [ ] Фото чека → записи
- [ ] Импорт банковской выписки
- [ ] Миграции базы через Alembic
