"""Выгрузка в Excel: лист «Записи» (его же можно загрузить обратно) и лист «По дням» —
как таблица на сайте: дни по строкам, категории по столбцам."""

import io
from collections import defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.categories import CATEGORIES, KINDS

TEAL = "0F4F54"
PAPER = "EEF1EC"
HEAD_FONT = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=TEAL)
TOTAL_FILL = PatternFill("solid", fgColor=PAPER)
RULE = Border(bottom=Side(style="thin", color="C9D3CC"))
MONEY = "#,##0;-#,##0;\"\""  # пустая клетка вместо нуля
MONEY_2 = "#,##0.##"
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _header(sheet, titles: list[str], widths: list[int]) -> None:
    sheet.append(titles)
    for i, width in enumerate(widths, start=1):
        cell = sheet.cell(row=1, column=i)
        cell.font, cell.fill = HEAD_FONT, HEAD_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(i)].width = width
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "A2"


def build_workbook(rows: list, title: str) -> bytes:
    """rows — записи (Transaction), отсортированные по дате."""
    book = Workbook()

    # ---- Записи: формат для обратной загрузки ----
    sheet = book.active
    sheet.title = "Записи"
    _header(sheet, ["Дата", "Тип", "Категория", "Сумма", "Описание", "Кто"], [12, 18, 24, 12, 40, 18])
    for r in rows:
        sheet.append([
            r.date,
            KINDS.get(r.kind, r.kind),
            CATEGORIES.get(r.category, CATEGORIES["other"])[0],
            float(r.amount),
            r.description or "",
            r.counterparty or "",
        ])
    for row in sheet.iter_rows(min_row=2):
        row[0].number_format = "DD.MM.YYYY"
        row[3].number_format = MONEY_2
    if rows:
        sheet.auto_filter.ref = f"A1:F{len(rows) + 1}"

    # ---- По дням: как таблица на сайте ----
    days = book.create_sheet("По дням")
    used = {r.category for r in rows if r.kind == "expense"}
    cats = [k for k, (_, kind) in CATEGORIES.items() if kind == "expense" and k in used]
    has_income = any(r.kind == "income" for r in rows)
    has_lend = any(r.kind == "lend" for r in rows)
    cols = [("_total", "Расходы за день")]
    if has_income:
        cols.append(("income", "Доход"))
    if has_lend:
        cols.append(("lend", "Дал в долг"))
    cols += [(k, CATEGORIES[k][0]) for k in cats]
    _header(days, ["Дата", "День"] + [t for _, t in cols], [12, 6] + [14 for _ in cols])
    days.freeze_panes = "C2"

    sums: dict[tuple[date, str], float] = defaultdict(float)
    for r in rows:
        key = r.category if r.kind == "expense" else r.kind
        sums[(r.date, key)] += float(r.amount)
        if r.kind == "expense":
            sums[(r.date, "_total")] += float(r.amount)
    for d in sorted({r.date for r in rows}):
        days.append([d, WEEKDAYS[d.weekday()]] + [sums.get((d, k)) or None for k, _ in cols])
        line = days.max_row
        days.cell(row=line, column=1).number_format = "DD.MM.YYYY"
        for i in range(len(cols)):
            cell = days.cell(row=line, column=3 + i)
            cell.number_format = MONEY
            cell.border = RULE
        days.cell(row=line, column=3).font = Font(bold=True)
        if d.weekday() >= 5:
            days.cell(row=line, column=2).font = Font(color="A3412F")

    last = days.max_row
    if last > 1:
        total = ["Итого", ""] + [f"=SUM({get_column_letter(3 + i)}2:{get_column_letter(3 + i)}{last})" for i in range(len(cols))]
        days.append(total)
        for cell in days[days.max_row]:
            cell.font, cell.fill = Font(bold=True), TOTAL_FILL
            cell.number_format = MONEY

    book.properties.title = title
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
