"""«Разбор месяца»: короткие выводы о том, куда ушли деньги.

Числа всегда считает приложение (SQL), а не модель: ИИ получает готовые факты
и только формулирует выводы. Без ИИ работают простые правила.
"""

from app.schemas import Debt, Summary

MONTHS_PREP = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе",
               "сентябре", "октябре", "ноябре", "декабре"]


def money(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " ₸"


# Категории, по которым ИИ не даёт советов экономить
NO_ADVICE = {"charity", "gift", "ten_percent", "sport", "books"}


def build_facts(summary: Summary, debts: list[Debt], counts: dict[str, int] | None = None) -> dict:
    counts = counts or {}
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
                "ключ": c.category,
                "название": c.name,
                "сумма": round(c.total),
                "записей": counts.get(c.category, 0),
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


def ai_payload(facts: dict) -> dict:
    """Факты для модели: суммы уже отформатированы, отсутствующих данных просто нет —
    модели нечего «додумывать» (например, сравнение с пустым прошлым месяцем)."""
    payload: dict = {
        "месяц": facts["месяц"],
        "доходы": money(facts["доходы"]),
        "расходы": money(facts["расходы"]),
        "категории_расходов": [
            {"название": c["название"], "сумма": money(c["сумма"]), "доля": f"{c['доля_процентов']}%",
             "сколько_раз": c["записей"]}
            for c in facts["категории"]
        ],
    }
    cmp = facts["сравнение"]
    if cmp["прошлый_месяц"]:
        payload["сравнение_с_прошлым_месяцем"] = {
            "период": cmp["период"], "сейчас": money(cmp["сейчас"]),
            "в " + facts["прошлый_месяц"]: money(cmp["прошлый_месяц"]),
        }
    limits = [c for c in facts["категории"] if c["лимит"]]
    if limits:
        payload["лимиты"] = [
            {"название": c["название"], "лимит": money(c["лимит"]), "потрачено": money(c["сумма"]),
             "превышен": c["сумма"] > c["лимит"]}
            for c in limits
        ]
    advice = [c for c in facts["категории"] if c["ключ"] not in NO_ADVICE and c["записей"] >= 2]
    if advice:
        payload["где_можно_советовать_экономию"] = [
            {"название": c["название"], "сумма": money(c["сумма"]), "сколько_раз": c["записей"]} for c in advice
        ]
    return payload


SYSTEM_PROMPT = """Ты помощник по личным финансам. Тебе дают готовые факты о месяце в JSON.
Все суммы уже посчитаны и отформатированы — копируй их как есть («22 000 ₸»), не пересчитывай и не придумывай.
Напиши 3–4 коротких вывода на русском языке, каждый — одно предложение до 25 слов:
1. Куда ушла основная часть денег.
2. Только если в фактах есть «сравнение_с_прошлым_месяцем» — что изменилось. Если его нет, про прошлый месяц не пиши.
3. Только если в фактах есть «лимиты» — про превышенные или почти исчерпанные. Если лимитов нет, про лимиты не пиши.
4. Только если есть «где_можно_советовать_экономию» — один конкретный совет по самой частой из этих трат,
   с примерной суммой экономии. Если такого списка нет, совет не давай.
Никогда не оценивай и не советуй сокращать благотворительность, подарки, спорт и учёбу. Не советуй инвестиции.
Ответь только JSON: {"points": ["...", "..."]}"""


def ai_insights(facts: dict) -> list[str]:
    import json

    from app.parser.ai import chat_json

    data = chat_json(SYSTEM_PROMPT, json.dumps(ai_payload(facts), ensure_ascii=False))
    points = [str(p).strip() for p in data.get("points", []) if str(p).strip()]
    return points[:5]
