import base64
import csv
import hashlib
import io
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import parser
from app.auth import get_current_user
from app.auth import router as auth_router
from app.categories import CATEGORIES, EXPENSE, KINDS, PERSON_KINDS, kind_of, normalize_category
from app.config import settings
from app.database import get_db
from app.excel import build_workbook
from app.importer import parse_csv, parse_xlsx
from app.insights import ai_insights, build_facts, rule_insights
from app.migrate import run_migrations
from app.parser.ai import AIParseError
from app.periods import compare_ranges, month_range
from app.parser.speech import MAX_BYTES as SPEECH_MAX_BYTES
from app.parser.speech import SpeechError, transcribe
from app.ratelimit import insights_limiter, speech_limiter
from app.personalize import build_examples
from app.models import Budget, Transaction, User
from app.schemas import (
    BudgetIn,
    BudgetOut,
    CategoryTotal,
    DayTotal,
    Debt,
    Insights,
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


run_migrations()

app = FastAPI(title="AI Finance Tracker", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(auth_router)


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def get_own_transaction(transaction_id: int, user: User, db: Session) -> Transaction:
    row = db.get(Transaction, transaction_id)
    # Чужая запись выглядит так же, как несуществующая
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Запись не найдена")
    return row


def _versioned_index() -> str:
    """index.html со ссылками вида app.js?v=<хеш файла>.

    Когда файл меняется, меняется и ссылка, поэтому браузер не берёт старую версию из кэша.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        digest = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{name}", f"/static/{name}?v={digest}")
    return html


INDEX_HTML = _versioned_index()
# Версия приложения для service worker: меняется при любом изменении страницы, стилей или скрипта
APP_VERSION = hashlib.sha256(INDEX_HTML.encode()).hexdigest()[:12]
SW_JS = (STATIC_DIR / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", APP_VERSION)


@app.get("/", include_in_schema=False)
def index():
    # Саму страницу браузер должен проверять каждый раз, чтобы сразу видеть новые версии файлов
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Отдаётся из корня, чтобы управлять всем сайтом; браузер должен проверять его при каждом заходе
    return Response(SW_JS, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "icons" / "favicon-32.png", media_type="image/png")


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_enabled": settings.ai_enabled, "stt_enabled": settings.stt_enabled,
            "version": APP_VERSION}


@app.post("/api/transcribe")
async def transcribe_voice(request: Request, user: User = Depends(get_current_user)):
    """Голос → текст (Whisper). Тело запроса — аудио как есть (audio/webm, audio/mp4 …)."""
    if not settings.stt_enabled:
        raise HTTPException(503, "Распознавание речи на сервере не настроено")
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("audio/"):
        raise HTTPException(415, "Нужен аудиофайл")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Пустая запись")
    if len(audio) > SPEECH_MAX_BYTES:
        raise HTTPException(413, "Запись слишком длинная — разбейте на части")
    key = f"user:{user.id}"
    if speech_limiter.is_blocked(key):
        raise HTTPException(429, "Слишком много голосовых записей подряд, попробуйте позже")
    speech_limiter.hit(key)
    try:
        text = await run_in_threadpool(transcribe, audio, content_type)
    except SpeechError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"text": text}


@app.get("/api/categories")
def categories():
    return {
        "categories": [
            {"key": key, "name": name, "kind": kind} for key, (name, kind) in CATEGORIES.items()
        ],
        "kinds": KINDS,
    }


def user_examples(user: User, db: Session) -> dict[str, str]:
    """Привычки пользователя «описание -> категория», свежие исправления первыми."""
    rows = db.execute(
        select(Transaction.description, Transaction.category)
        .where(Transaction.user_id == user.id, Transaction.description != "")
        .order_by(func.coalesce(Transaction.updated_at, Transaction.created_at).desc(), Transaction.id.desc())
        .limit(500)
    ).all()
    return build_examples(rows)


@app.post("/api/parse", response_model=ParseResponse)
def parse_text(body: ParseRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Превращает свободный текст в записи. Ничего не сохраняет — только предпросмотр."""
    return parser.parse(body.text, body.date, user_examples(user, db))


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
            counterparty=item.counterparty,
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
def import_file(body: ImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Загрузка Excel или CSV в формате выгрузки. Если в файле есть ошибки, не сохраняется ничего."""
    if body.xlsx:
        try:
            data = base64.b64decode(body.xlsx, validate=True)
        except ValueError:
            raise HTTPException(422, "Файл повреждён, попробуйте выбрать его ещё раз") from None
        items, errors = parse_xlsx(data)
    elif body.csv:
        items, errors = parse_csv(body.csv)
    else:
        raise HTTPException(422, "Нет файла")
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
            counterparty=item.counterparty,
            raw_text="импорт файла",
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
    # Имя человека имеет смысл только для долгов
    if row.kind not in PERSON_KINDS:
        row.counterparty = None
    elif row.counterparty is not None:
        row.counterparty = row.counterparty.strip() or None
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


def _sum_by(db: Session, column, *where):
    rows = db.execute(select(column, func.sum(Transaction.amount)).where(*where).group_by(column)).all()
    return {key: float(total or 0) for key, total in rows}


@app.get("/api/summary", response_model=Summary)
def summary(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    month = month or current_month()
    start, end = month_range(month)
    mine = Transaction.user_id == user.id
    scope = (mine, Transaction.date >= start, Transaction.date < end)

    totals = _sum_by(db, Transaction.category, *scope)
    by_kind = _sum_by(db, Transaction.kind, *scope)

    cur_start, cur_end, prev_start, prev_end, compare_days = compare_ranges(month, date.today())
    expense_only = Transaction.kind == EXPENSE
    cur_by_cat = _sum_by(db, Transaction.category, mine, expense_only,
                         Transaction.date >= cur_start, Transaction.date < cur_end)
    prev_by_cat = _sum_by(db, Transaction.category, mine, expense_only,
                          Transaction.date >= prev_start, Transaction.date < prev_end)
    limits = {
        b.category: float(b.monthly_limit)
        for b in db.scalars(select(Budget).where(Budget.user_id == user.id))
    }

    by_category = sorted(
        (
            CategoryTotal(
                category=cat,
                name=CATEGORIES.get(cat, CATEGORIES["other"])[0],
                kind=kind_of(cat),
                total=total,
                limit=limits.get(cat),
                prev_total=prev_by_cat.get(cat, 0.0),
            )
            for cat, total in totals.items()
        ),
        key=lambda c: -c.total,
    )
    # Категории с лимитом, но без трат в этом месяце — тоже показываем
    for cat, limit in limits.items():
        if cat not in totals:
            by_category.append(
                CategoryTotal(category=cat, name=CATEGORIES.get(cat, CATEGORIES["other"])[0],
                              kind=kind_of(cat), total=0, limit=limit, prev_total=prev_by_cat.get(cat, 0.0))
            )

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
        elif kind == EXPENSE:
            entry.expense += float(total or 0)

    income = by_kind.get("income", 0.0)
    expense = by_kind.get(EXPENSE, 0.0)
    lent = by_kind.get("lend", 0.0)
    repaid = by_kind.get("repaid", 0.0)
    return Summary(
        month=month,
        income=income,
        expense=expense,
        lent=lent,
        repaid=repaid,
        balance=round(income - expense - lent + repaid, 2),
        by_category=by_category,
        by_day=list(days.values()),
        prev_month=prev_start.strftime("%Y-%m"),
        compare_days=compare_days,
        expense_to_date=sum(cur_by_cat.values()),
        prev_expense=sum(prev_by_cat.values()),
    )


# ---------- Долги ----------

@app.get("/api/debts", response_model=list[Debt])
def debts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Кто сколько должен — по всем месяцам. Имена сравниваются без учёта регистра."""
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.kind.in_(sorted(PERSON_KINDS)))
        .order_by(Transaction.date, Transaction.id)
    ).all()
    people: dict[str, Debt] = {}
    for row in rows:
        name = (row.counterparty or "").strip() or "Без имени"
        debt = people.get(name.casefold())
        if debt is None:
            debt = people[name.casefold()] = Debt(person=name, lent=0, repaid=0, balance=0, since=row.date, last=row.date)
        amount = float(row.amount)
        if row.kind == "lend":
            debt.lent += amount
        else:
            debt.repaid += amount
        debt.last = row.date
        debt.balance = round(debt.lent - debt.repaid, 2)
    return sorted(people.values(), key=lambda d: (-d.balance, d.person))


@app.delete("/api/debts")
def delete_debt(
    person: str = Query(min_length=1, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удаляет долг целиком: все записи «дал в долг» и «вернул» с этим человеком (за все месяцы)."""
    key = person.strip().casefold()
    rows = db.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.kind.in_(sorted(PERSON_KINDS)))
    ).all()
    doomed = [r for r in rows if ((r.counterparty or "").strip() or "Без имени").casefold() == key]
    if not doomed:
        raise HTTPException(404, "Такого долга нет")
    for row in doomed:
        db.delete(row)
    db.commit()
    return {"deleted": len(doomed)}


# ---------- Разбор месяца ----------

@app.post("/api/insights", response_model=Insights)
def insights(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Выводы о месяце. Числа считает приложение, ИИ только формулирует."""
    month = month or current_month()
    start, end = month_range(month)
    counts = dict(db.execute(
        select(Transaction.category, func.count())
        .where(Transaction.user_id == user.id, Transaction.date >= start, Transaction.date < end)
        .group_by(Transaction.category)
    ).all())
    expense_cats = [k for k, (_, kind) in CATEGORIES.items() if kind == "expense"]
    top = db.execute(
        select(Transaction.description, Transaction.category, Transaction.amount, Transaction.date)
        .where(Transaction.user_id == user.id, Transaction.date >= start, Transaction.date < end,
               Transaction.category.in_(expense_cats))
        .order_by(Transaction.amount.desc()).limit(3)
    ).all()
    big = [{"описание": d or "", "категория": CATEGORIES[c][0], "сумма": float(a), "дата": dt.strftime("%d.%m")}
           for d, c, a, dt in top]
    facts = build_facts(summary(month=month, user=user, db=db), debts(user=user, db=db), counts, big)
    if not facts["категории"] or not settings.ai_enabled:
        return Insights(source="rules", points=rule_insights(facts))

    key = str(user.id)
    if insights_limiter.is_blocked(key):
        return Insights(source="rules", points=rule_insights(facts),
                        warning="Разбор от ИИ доступен 10 раз в час, показаны простые выводы")
    insights_limiter.hit(key)
    try:
        points = ai_insights(facts)
        if points:
            return Insights(source="ai", points=points)
        warning = "ИИ не ответил, показаны простые выводы"
    except AIParseError as exc:
        warning = f"{exc}. Показаны простые выводы"
    return Insights(source="rules", points=rule_insights(facts), warning=warning)


# ---------- Лимиты ----------

@app.get("/api/budgets", response_model=list[BudgetOut])
def list_budgets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        BudgetOut(category=b.category, name=CATEGORIES.get(b.category, CATEGORIES["other"])[0], limit=float(b.monthly_limit))
        for b in db.scalars(select(Budget).where(Budget.user_id == user.id).order_by(Budget.category))
    ]


@app.put("/api/budgets/{category}", response_model=list[BudgetOut])
def set_budget(
    category: str, body: BudgetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Задать месячный лимит. Пустой или нулевой лимит удаляет его."""
    if category not in CATEGORIES or kind_of(category) != EXPENSE:
        raise HTTPException(400, "Лимит можно задать только для категории расходов")
    budget = db.scalar(select(Budget).where(Budget.user_id == user.id, Budget.category == category))
    if not body.limit:
        if budget is not None:
            db.delete(budget)
    elif budget is None:
        db.add(Budget(user_id=user.id, category=category, monthly_limit=body.limit))
    else:
        budget.monthly_limit = body.limit
    db.commit()
    return list_budgets(user=user, db=db)


@app.get("/api/export.xlsx")
def export_xlsx(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    all_time: bool = Query(default=False, alias="all", description="Все записи за всё время"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Excel: лист «Записи» (можно загрузить обратно) и лист «По дням»."""
    if all_time:
        rows = list(db.scalars(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date, Transaction.id)
        ))
        name, title = "finance-all", "Финансы — все записи"
    else:
        month = month or current_month()
        rows = list(reversed(_month_rows(month, user, db)))
        name, title = f"finance-{month}", f"Финансы — {month}"
    return Response(
        content=build_workbook(rows, title),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
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
    writer.writerow(["Дата", "Тип", "Категория", "Сумма", "Описание", "Кто"])
    for row in reversed(_month_rows(month, user, db)):
        writer.writerow(
            [
                row.date.isoformat(),
                KINDS.get(row.kind, row.kind),
                CATEGORIES.get(row.category, CATEGORIES["other"])[0],
                str(row.amount).replace(".", ","),
                row.description,
                row.counterparty or "",
            ]
        )
    # BOM, чтобы Excel правильно открыл кириллицу
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="finance-{month}.csv"'},
    )
