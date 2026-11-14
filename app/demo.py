"""Демо-аккаунт: вход одной кнопкой с правдоподобными данными за текущий и прошлый месяц.

При каждом входе данные демо-аккаунта создаются заново, поэтому то,
что поменял один посетитель, не увидит следующий надолго.
"""

import random
import secrets
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.categories import CATEGORIES
from app.models import Budget, Transaction, User
from app.security import hash_password

DEMO_EMAIL = "demo@finance.demo"

# (категория, варианты описаний, мин, макс, вероятность в день) — будни обычного студента
DAILY = [
    ("products", ["Magnum: продукты", "Small: продукты", "продукты на неделю", "молоко и хлеб"], 900, 5200, 0.38),
    ("vegetables", ["овощи и фрукты", "яблоки и бананы", "овощи на базаре"], 400, 1600, 0.25),
    ("convenience", ["магазин у дома", "вода и снеки", "сок и печенье"], 300, 1200, 0.3),
    ("cafe", ["кофе", "обед в столовой", "самса", "кофе с другом", "шаурма"], 500, 2200, 0.45),
    ("transport", ["такси до универа", "такси домой", "Яндекс Такси"], 700, 2200, 0.28),
    ("transport", ["автобус"], 120, 120, 0.45),
    ("charity", ["пожертвование"], 300, 1000, 0.12),
]
MONTHLY = [
    (2, "other", "мобильная связь", 3500),
    (3, "household", "порошок и губки", 2600),
    (6, "other", "подписка на музыку", 1890),
    (8, "laundry", "прачечная", 1400),
    (11, "books", "курс по Python", 7900),
    (12, "sport", "абонемент в зал", 15000),
    (16, "cafe", "день рождения друга, кафе", 8500),
    (18, "clothes", "кроссовки", 24000),
    (21, "gift", "подарок маме", 9000),
    (27, "household", "лампа на стол", 6400),
]
LIMITS = {"transport": 25000, "cafe": 20000, "products": 35000}


def _round(value: float, step: int = 10) -> Decimal:
    return Decimal(int(round(value / step) * step))


def _month_rows(user_id: int, first: date, last: date, rng: random.Random) -> list[Transaction]:
    rows: list[Transaction] = []

    def add(day: date, category: str, amount: Decimal, description: str, person: str | None = None):
        rows.append(Transaction(
            user_id=user_id, date=day, amount=amount, category=category, kind=CATEGORIES[category][1],
            description=description, counterparty=person, raw_text="демо",
        ))

    day = first
    while day <= last:
        for category, texts, low, high, chance in DAILY:
            if rng.random() < chance:
                add(day, category, _round(rng.uniform(low, high), 50 if high > 1000 else 10), rng.choice(texts))
        day += timedelta(days=1)

    for dom, category, text, amount in MONTHLY:
        if dom <= last.day:
            add(first.replace(day=dom), category, Decimal(amount), text)
    if last.day >= 1:
        add(first, "income", Decimal(42000), "стипендия")
    if last.day >= 10:
        add(first.replace(day=10), "income", Decimal(150000), "зарплата: подработка")
    if last.day >= 22:
        add(first.replace(day=22), "income", Decimal(30000), "фриланс: сайт для кофейни")
    if last.day >= 9:
        add(first.replace(day=9), "lend", Decimal(10000), "", "Айбек")
    if last.day >= 14:
        add(first.replace(day=14), "lend", Decimal(5000), "", "Дана")
    if last.day >= 24:
        add(first.replace(day=24), "repaid", Decimal(5000), "", "Дана")
    return rows


def seed_demo(db: Session, today: date | None = None) -> User:
    """Создаёт (или пересоздаёт) демо-пользователя с данными за прошлый и текущий месяц."""
    today = today or date.today()
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        # Пароль случайный и нигде не хранится: войти можно только кнопкой «Демо»
        user = User(email=DEMO_EMAIL, password_hash=hash_password(secrets.token_urlsafe(24)))
        db.add(user)
        db.flush()
    db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    db.execute(delete(Budget).where(Budget.user_id == user.id))

    rng = random.Random(f"{today.year}-{today.month}")
    this_first = today.replace(day=1)
    prev_last = this_first - timedelta(days=1)
    rows = _month_rows(user.id, prev_last.replace(day=1), prev_last, rng)
    rows += _month_rows(user.id, this_first, today, rng)
    db.add_all(rows)
    db.add_all(Budget(user_id=user.id, category=c, monthly_limit=Decimal(v)) for c, v in LIMITS.items())
    db.commit()
    db.refresh(user)
    return user
