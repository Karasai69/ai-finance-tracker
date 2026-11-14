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

# (категория, описание, мин, макс, вероятность в день)
DAILY = [
    ("products", "продукты", 900, 4200, 0.45),
    ("vegetables", "овощи и фрукты", 300, 1400, 0.3),
    ("convenience", "магазин у дома", 250, 1300, 0.35),
    ("cafe", "самса", 300, 700, 0.25),
    ("cafe", "кофе", 600, 1200, 0.15),
    ("transport", "такси", 600, 2200, 0.35),
    ("transport", "автобус", 100, 100, 0.4),
    ("charity", "садака", 200, 1000, 0.5),
    ("nuts", "орехи", 300, 900, 0.1),
]
MONTHLY = [
    (3, "household", "порошок и губки", 2400),
    (7, "laundry", "прачечная", 1200),
    (10, "books", "книга по алгоритмам", 6500),
    (12, "sport", "абонемент в зал", 15000),
    (18, "clothes", "кроссовки", 18000),
    (21, "gift", "подарок маме", 9000),
    (25, "other", "мобильная связь", 3500),
]
LIMITS = {"transport": 15000, "cafe": 8000, "products": 30000}


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
        for category, text, low, high, chance in DAILY:
            if rng.random() < chance:
                add(day, category, _round(rng.uniform(low, high), 50 if high > 1000 else 10), text)
        day += timedelta(days=1)

    for dom, category, text, amount in MONTHLY:
        if dom <= last.day:
            add(first.replace(day=dom), category, Decimal(amount), text)
    if last.day >= 5:
        add(first.replace(day=5), "income", Decimal(180000), "стипендия и подработка")
    if last.day >= 20:
        add(first.replace(day=20), "income", Decimal(40000), "брат прислал")
        add(first.replace(day=20), "ten_percent", Decimal(4000), "10% от дохода")
    if last.day >= 9:
        add(first.replace(day=9), "lend", Decimal(15000), "", "Алижан")
    if last.day >= 14:
        add(first.replace(day=14), "lend", Decimal(5000), "", "Мадияр")
    if last.day >= 24:
        add(first.replace(day=24), "repaid", Decimal(5000), "", "Мадияр")
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
