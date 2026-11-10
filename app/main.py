import csv
import io
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app import parser
from app.auth import get_current_user
from app.auth import router as auth_router
from app.categories import CATEGORIES, KINDS, kind_of, normalize_category
from app.config import settings
from app.database import Base, engine, get_db
from app.importer import parse_csv
from app.models import Transaction, User
from app.schemas import (
    CategoryTotal,
    DayTotal,
    ImportRequest,
    ImportResponse,
    ParseRequest,
    ParseResponse,
    SaveRequest,
    Summary,
    TransactionOut,
    TransactionUpdate,
)

STATIC_DIR = Path(__file__).parent / "static"
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def check_old_schema() -> None:
    """База из версии без аккаунтов не подходит: в ней нет колонки user_id."""
    tables = inspect(engine)
    if tables.has_table("transactions"):
        columns = {col["name"] for col in tables.get_columns("transactions")}
        if "user_id" not in columns:
            raise RuntimeError(
                "База данных создана старой версией приложения (без аккаунтов). "
                "Удалите файл finance.db и запустите снова."
            )


check_old_schema()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Finance Tracker", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(auth_router)


def month_range(month: str) -> tuple[date, date]:
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def get_own_transaction(transaction_id: int, user: User, db: Session) -> Transaction:
    row = db.get(Transaction, transaction_id)
    # Чужая запись выглядит так же, как несуществующая
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Запись не найдена")
    return row


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_enabled": settings.ai_enabled}


@app.get("/api/categories")
def categories():
    return {
        "categories": [
            {"key": key, "name": name, "kind": kind} for key, (name, kind) in CATEGORIES.items()
        ],
        "kinds": KINDS,
    }


@app.post("/api/parse", response_model=ParseResponse)
def parse_text(body: ParseRequest, user: User = Depends(get_current_user)):
    """Превращает свободный текст в записи. Ничего не сохраняет — только предпросмотр."""
    return parser.parse(body.text, body.date)


@app.post("/api/transactions", response_model=list[TransactionOut], status_code=201)
def create_transactions(
    body: SaveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rows = [
        Transaction(
            user_id=user.id,
            date=item.date,
            amount=item.amount,
            category=item.category,
            kind=item.kind,
            description=item.description,
            raw_text=body.raw_text,
        )
        for item in body.items
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@app.post("/api/import", response_model=ImportResponse, status_code=201)
def import_csv(body: ImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Загрузка CSV в формате выгрузки. Если в файле есть ошибки, не сохраняется ничего."""
    items, errors = parse_csv(body.csv)
    if errors:
        shown = "; ".join(errors[:5]) + (f" и ещё {len(errors) - 5}" if len(errors) > 5 else "")
        raise HTTPException(422, f"Файл не загружен: {shown}")
    if not items:
        raise HTTPException(422, "В файле нет записей")
    db.add_all(
        Transaction(
            user_id=user.id,
            date=item.date,
            amount=item.amount,
            category=item.category,
            kind=item.kind,
            description=item.description,
            raw_text="импорт CSV",
        )
        for item in items
    )
    db.commit()
    months = sorted({item.date.strftime("%Y-%m") for item in items})
    return ImportResponse(imported=len(items), months=months)


def _month_rows(month: str, user: User, db: Session) -> list[Transaction]:
    start, end = month_range(month)
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.date >= start, Transaction.date < end)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    return list(db.scalars(stmt).all())


@app.get("/api/transactions", response_model=list[TransactionOut])
def list_transactions(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _month_rows(month or current_month(), user, db)


@app.patch("/api/transactions/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = get_own_transaction(transaction_id, user, db)
    data = body.model_dump(exclude_unset=True)
    if "category" in data:
        data["category"] = normalize_category(data["category"])
        data["kind"] = kind_of(data["category"])
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@app.delete("/api/transactions/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = get_own_transaction(transaction_id, user, db)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@app.get("/api/summary", response_model=Summary)
def summary(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    month = month or current_month()
    start, end = month_range(month)
    scope = (Transaction.user_id == user.id, Transaction.date >= start, Transaction.date < end)

    by_category_rows = db.execute(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(*scope)
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
    ).all()
    by_category = [
        CategoryTotal(
            category=cat,
            name=CATEGORIES.get(cat, CATEGORIES["other"])[0],
            kind=kind_of(cat),
            total=float(total or 0),
        )
        for cat, total in by_category_rows
    ]

    by_kind = {
        kind: float(total or 0)
        for kind, total in db.execute(
            select(Transaction.kind, func.sum(Transaction.amount)).where(*scope).group_by(Transaction.kind)
        ).all()
    }

    days: dict[date, DayTotal] = {}
    for day, kind, total in db.execute(
        select(Transaction.date, Transaction.kind, func.sum(Transaction.amount))
        .where(*scope)
        .group_by(Transaction.date, Transaction.kind)
        .order_by(Transaction.date)
    ).all():
        entry = days.setdefault(day, DayTotal(date=day, expense=0, income=0))
        if kind == "income":
            entry.income += float(total or 0)
        elif kind == "expense":
            entry.expense += float(total or 0)

    income = by_kind.get("income", 0.0)
    expense = by_kind.get("expense", 0.0)
    lent = by_kind.get("lend", 0.0)
    return Summary(
        month=month,
        income=income,
        expense=expense,
        lent=lent,
        balance=round(income - expense - lent, 2),
        by_category=by_category,
        by_day=list(days.values()),
    )


@app.get("/api/export.csv")
def export_csv(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """CSV для Excel и Google Sheets."""
    month = month or current_month()
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Дата", "Тип", "Категория", "Сумма", "Описание"])
    for row in reversed(_month_rows(month, user, db)):
        writer.writerow(
            [
                row.date.isoformat(),
                KINDS.get(row.kind, row.kind),
                CATEGORIES.get(row.category, CATEGORIES["other"])[0],
                str(row.amount).replace(".", ","),
                row.description,
            ]
        )
    # BOM, чтобы Excel правильно открыл кириллицу
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="finance-{month}.csv"'},
    )
