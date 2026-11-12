"""«Разбор месяца»: короткие выводы о том, куда ушли деньги.

Числа всегда считает приложение (SQL), а не модель: ИИ получает готовые факты
и только формулирует выводы. Без ИИ работают простые правила.
"""

from app.schemas import Debt, Summary

MONTHS_PREP = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе",
               "сентябре", "октябре", "ноябре", "декабре"]


def money(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " ₸"


def build_facts(summary: Summary, debts: list[Debt]) -> dict:
    expenses = [c for c in summary.by_category if c.kind == "expense" and c.total > 0]
    month_name = MONTHS_PREP[int(summary.month[5:7]) - 1]
    prev_name = MONTHS_PREP[int(summary.prev_month[5:7]) - 1]
    days = summary.compare_days
    return {
        "месяц": month_name,
        "прошлый_месяц": prev_name,
        "доходы": round(summary.income),
        "расходы": round(summary.expense),
        "остаток": round(summary.balance),
        "сравнение": {
            "период": f"1–{days} число" if days else "месяц целиком",
            "сейчас": round(summary.expense_to_date),
            "прошлый_месяц": round(summary.prev_expense),
        },
        "категории": [
            {
                "название": c.name,
                "сумма": round(c.total),
                "доля_процентов": round(c.total / summary.expense * 100) if summary.expense else 0,
                "прошлый_месяц": round(c.prev_total),
                "лимит": round(c.limit) if c.limit else None,
            }
            for c in expenses[:8]
        ],
        "мне_должны": round(sum(d.balance for d in debts if d.balance > 0)),
        "должники": [d.person for d in debts if d.balance > 0][:5],
    }


def rule_insights(facts: dict) -> list[str]:
    """Выводы без ИИ — на случай, если модель не настроена или недоступна."""
    points: list[str] = []
    cats = facts["категории"]
    if not cats:
        return [f"В {facts['месяц']} расходов пока нет."]
    top = cats[0]
    points.append(f"Больше всего ушло на «{top['название']}»: {money(top['сумма'])}, это {top['доля_процентов']}% всех расходов.")

    over = [c for c in cats if c["лимит"] and c["сумма"] > c["лимит"]]
    for c in over[:2]:
        points.append(f"Лимит «{c['название']}» превышен на {money(c['сумма'] - c['лимит'])}.")

    cmp = facts["сравнение"]
    if cmp["прошлый_месяц"]:
        diff = cmp["сейчас"] - cmp["прошлый_месяц"]
        pct = round(abs(diff) / cmp["прошлый_месяц"] * 100)
        word = "больше" if diff > 0 else "меньше"
        points.append(f"Расходы на {pct}% {word}, чем за тот же период в {facts['прошлый_месяц']}.")
        grown = [c for c in cats if c["прошлый_месяц"] and c["сумма"] > c["прошлый_месяц"] * 1.3]
        if grown:
            g = max(grown, key=lambda c: c["сумма"] - c["прошлый_месяц"])
            points.append(f"Сильнее всего выросла категория «{g['название']}»: {money(g['прошлый_месяц'])} → {money(g['сумма'])}.")

    if facts["мне_должны"]:
        points.append(f"Вам должны {money(facts['мне_должны'])}: {', '.join(facts['должники'])}.")
    return points[:4]


SYSTEM_PROMPT = """Ты помощник по личным финансам. Тебе дают готовые факты о месяце в JSON —
все числа уже посчитаны, не пересчитывай и не придумывай новые.
Напиши 3–4 коротких вывода на русском языке (каждый — одно предложение до 25 слов):
- куда ушла основная часть денег;
- что изменилось по сравнению с прошлым месяцем (если есть данные);
- превышенные лимиты (если есть);
- один конкретный и выполнимый совет, где можно сэкономить.
Не осуждай траты, не давай советов по благотворительности, подаркам и религиозным расходам,
не советуй инвестиции. Суммы пиши в тенге со знаком ₸.
Ответь только JSON: {"points": ["...", "..."]}"""


def ai_insights(facts: dict) -> list[str]:
    import json

    from app.parser.ai import chat_json

    data = chat_json(SYSTEM_PROMPT, json.dumps(facts, ensure_ascii=False))
    points = [str(p).strip() for p in data.get("points", []) if str(p).strip()]
    return points[:5]
