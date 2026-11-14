// Веб-интерфейс трекера: ввод текстом или голосом, предпросмотр, таблица и список записей.

const $ = (id) => document.getElementById(id);
const state = {
  categories: [],
  names: {},
  order: {},
  preview: [],
  rawText: "",
  month: "",
  rows: [],
  view: "table",
  user: null,
  authMode: "login",
  kinds: {},      // категория -> тип (expense, income, lend, repaid)
  summary: null,
  debts: [],
};

const PERSON_KINDS = ["lend", "repaid"];
// Всё, что не расход: подпись, знак и стиль
const KIND_INFO = {
  income: { label: "Доход", sign: "+" },
  lend: { label: "Дал в долг", sign: "→ " },
  repaid: { label: "Вернули долг", sign: "+" },
  save: { label: "Отложил", sign: "→ " },
  unsave: { label: "Взял из накоплений", sign: "+" },
};
const kindSign = (kind) => KIND_INFO[kind]?.sign || "";
const kindLabel = (row) => {
  const info = KIND_INFO[row.kind];
  if (!info) return state.names[row.category] || row.category;
  return row.counterparty ? `${info.label}: ${row.counterparty}` : info.label;
};
const isPersonKind = (category) => PERSON_KINDS.includes(state.kinds[category]);

const fmt = (value) => Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
const money = (value) => fmt(value).replace("-", "−") + " ₸";

const todayISO = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}) {
  if (!navigator.onLine) throw new Error("Нет интернета — проверьте связь и попробуйте ещё раз");
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    showAuth();
    throw new Error("Нужно войти в аккаунт");
  }
  if (!response.ok) {
    let message = `Ошибка сервера (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
        // Ошибка проверки данных (422): берём текст первой ошибки
        message = data.detail[0].msg.replace(/^Value error, /, "");
      }
    } catch (_) { /* тело не JSON */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

const storage = {
  get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* недоступно */ } },
};

// ---------- Месяц ----------

function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  const name = new Date(y, m - 1, 1).toLocaleDateString("ru-RU", { month: "long" });
  return `${name[0].toUpperCase()}${name.slice(1)} ${y}`;
}

function setMonth(month) {
  if (month !== state.month) resetReview();
  state.month = month;
  $("month-label").textContent = monthLabel(month);
  $("ledger-title").textContent = monthLabel(month).split(" ")[0];
  $("export").href = `/api/export.xlsx?month=${month}`;
  refresh();
}

// ---------- Предпросмотр ----------

function categorySelect(value, onChange) {
  const select = el("select", { "aria-label": "Категория", onchange: (e) => onChange(e.target.value) });
  for (const cat of state.categories) {
    select.append(el("option", { value: cat.key, selected: cat.key === value ? "" : null }, cat.name));
  }
  return select;
}

function renderPreview() {
  const box = $("preview-items");
  box.replaceChildren();
  state.preview.forEach((item, index) => {
    box.append(
      el("div", { class: "preview-item" },
        el("input", { type: "date", value: item.date, "aria-label": "Дата",
          onchange: (e) => (item.date = e.target.value) }),
        categorySelect(item.category, (value) => {
          const hadPerson = isPersonKind(item.category);
          item.category = value;
          if (hadPerson !== isPersonKind(value)) renderPreview(); // показать или убрать поле «Кто»
        }),
        el("input", { type: "number", min: "0", step: "any", value: item.amount, "aria-label": "Сумма",
          onchange: (e) => (item.amount = Number(e.target.value)) }),
        el("div", { class: "desc" },
          el("input", { type: "text", value: item.description, "aria-label": "Описание", placeholder: "Описание",
            onchange: (e) => (item.description = e.target.value) }),
          isPersonKind(item.category)
            ? el("input", { type: "text", class: "person", value: item.counterparty || "", "aria-label": "Кто",
                placeholder: "Кто", maxlength: "100", onchange: (e) => (item.counterparty = e.target.value) })
            : null,
        ),
        el("button", { type: "button", class: "icon-btn", title: "Убрать из списка", "aria-label": "Убрать из списка",
          onclick: () => { state.preview.splice(index, 1); renderPreview(); } }, "×"),
      ),
    );
  });
  $("preview").hidden = state.preview.length === 0;
}

async function parseText() {
  const text = $("text").value.trim();
  if (!text) return setStatus("Напишите, что потратили, например: такси 300");
  $("parse").disabled = true;
  setStatus("Разбираю…");
  try {
    const result = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ text, date: $("date").value || null }),
    });
    state.preview = result.items;
    state.rawText = text;
    $("source").textContent = (result.source === "ai" ? "(разобрал ИИ" : "(простой разбор")
      + (result.learned ? `, учтены ваши прошлые исправления: ${result.learned})` : ")");
    renderPreview();
    const notes = [];
    if (!result.items.length) notes.push("Не нашёл сумм в тексте. Добавьте число, например: такси 300");
    if (result.unparsed.length) notes.push("Без суммы: " + result.unparsed.join(", "));
    if (result.warning) notes.push(result.warning);
    setStatus(notes.join(". "), !result.items.length);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    $("parse").disabled = false;
  }
}

async function savePreview() {
  const items = state.preview.filter((item) => item.amount > 0);
  if (!items.length) return setStatus("Нечего сохранять: у записей нет суммы", true);
  $("save").disabled = true;
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify({ items, raw_text: state.rawText }) });
    state.preview = [];
    renderPreview();
    $("text").value = "";
    $("text").style.height = "";
    const savedMonth = items[0].date.slice(0, 7);
    if (savedMonth !== state.month) {
      state.month = savedMonth;
      $("month-label").textContent = monthLabel(savedMonth);
    }
    await refresh();
    const warnings = limitWarnings(new Set(items.map((i) => i.category)));
    setStatus([`Сохранено записей: ${items.length}`, ...warnings].join(". "), warnings.some((w) => w.includes("превышен")));
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    $("save").disabled = false;
  }
}

// ---------- Итоги ----------

const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
  "сентября", "октября", "ноября", "декабря"];
const MONTHS_PREP = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе",
  "сентябре", "октябре", "ноябре", "декабре"];

function periodLabel(month, days) {
  const m = Number(month.slice(5, 7)) - 1;
  return days ? `за ${days === 1 ? "1" : `1–${days}`} ${MONTHS_GEN[m]}` : `в ${MONTHS_PREP[m]}`;
}

function renderComparison(summary) {
  const chip = $("compare");
  const days = summary.compare_days;
  chip.className = "compare-chip";
  if (!summary.expense_to_date && !summary.prev_expense) { chip.hidden = true; return; }
  const now = periodLabel(summary.month, days);
  const before = periodLabel(summary.prev_month, days);
  chip.hidden = false;
  if (!summary.prev_expense) {
    chip.classList.add("flat");
    chip.textContent = `${before[0].toUpperCase()}${before.slice(1)} записей нет`;
    chip.title = `Расходы ${now}: ${money(summary.expense_to_date)}`;
    return;
  }
  const diff = summary.expense_to_date - summary.prev_expense;
  const pct = Math.round(Math.abs(diff) / summary.prev_expense * 100);
  const prevMonth = MONTHS_GEN[Number(summary.prev_month.slice(5, 7)) - 1];
  if (pct === 0) chip.classList.add("flat");
  else if (diff > 0) chip.classList.add("up");
  chip.textContent = pct === 0
    ? `расходы как в ${MONTHS_PREP[Number(summary.prev_month.slice(5, 7)) - 1]}`
    : `расходы на ${pct}% ${diff > 0 ? "больше" : "меньше"} ${prevMonth}`;
  chip.title = `Расходы ${now}: ${money(summary.expense_to_date)}, ${before}: ${money(summary.prev_expense)}`;
}

function limitWarnings(categories) {
  if (!state.summary) return [];
  const out = [];
  for (const cat of state.summary.by_category) {
    if (!cat.limit || (categories && !categories.has(cat.category))) continue;
    if (cat.total > cat.limit) out.push(`Лимит «${cat.name}» превышен: ${money(cat.total)} из ${money(cat.limit)}`);
    else if (cat.total >= cat.limit * 0.9) out.push(`Лимит «${cat.name}» почти исчерпан: осталось ${money(cat.limit - cat.total)}`);
  }
  return out;
}

function renderSummary(summary) {
  state.summary = summary;
  $("sum-income").textContent = (summary.income ? "+" : "") + money(summary.income);
  $("sum-expense").textContent = (summary.expense ? "−" : "") + money(summary.expense);
  $("sum-lent").textContent = money(summary.lent);
  $("sum-repaid").textContent = money(summary.repaid);
  $("repaid-box").hidden = !summary.repaid;
  $("sum-saved").textContent = money(summary.saved || 0);
  $("sum-saved-total").textContent = summary.savings_total ? `всего ${money(summary.savings_total)}` : "";
  $("savings-total").textContent = money(summary.savings_total || 0);
  $("savings-month").textContent = (summary.saved > 0 ? "+" : "") + money(summary.saved || 0);
  $("savings-month-label").textContent = `В ${MONTHS_PREP[Number(summary.month.slice(5, 7)) - 1]}`;
  // Знак ₸ — отдельно, мельче и цветом охры, как номинал на купюре
  $("sum-balance").replaceChildren(fmt(summary.balance).replace("-", "−"), el("span", { class: "cur" }, "₸"));
  $("sum-balance").classList.toggle("negative", summary.balance < 0);
  renderComparison(summary);
  renderDailyChart(summary);

  const expenses = summary.by_category.filter((c) => c.kind === "expense");
  const scale = Math.max(...expenses.map((c) => Math.max(c.total, c.limit || 0)), 1);
  const showDelta = summary.prev_expense > 0;
  const prevName = MONTHS_PREP[Number(summary.prev_month.slice(5, 7)) - 1];
  const box = $("categories");
  box.replaceChildren();
  if (!expenses.length) {
    box.append(el("p", { class: "empty" }, "В этом месяце расходов нет."));
    return;
  }
  for (const cat of expenses) {
    const pct = summary.expense ? (cat.total / summary.expense) * 100 : 0;
    const share = pct > 0 && pct < 1 ? "<1" : Math.round(pct);
    const over = cat.limit && cat.total > cat.limit;
    const near = cat.limit && !over && cat.total >= cat.limit * 0.9;
    const fill = el("div", { class: `bar-fill${over ? " over" : near ? " near" : ""}` });
    fill.style.width = `${(cat.total / scale) * 100}%`;
    const track = el("div", { class: "bar-track" }, fill);
    if (cat.limit) {
      const mark = el("span", { class: "bar-limit", tabindex: "0", "aria-label": `Лимит ${money(cat.limit)}`,
        "data-tip": `Лимит ${money(cat.limit)}` });
      mark.style.left = `${(cat.limit / scale) * 100}%`;
      track.append(mark);
    }
    let note = null;
    if (cat.limit) {
      note = over
        ? el("span", { class: "bar-note over" }, `⚠ превышен на ${money(cat.total - cat.limit)} (лимит ${money(cat.limit)})`)
        : el("span", { class: `bar-note${near ? " near" : ""}` }, `${near ? "⚠ " : ""}осталось ${money(cat.limit - cat.total)} из ${money(cat.limit)}`);
    }
    let delta = null;
    if (showDelta && cat.total && cat.prev_total) {
      const d = Math.round(((cat.total - cat.prev_total) / cat.prev_total) * 100);
      delta = el("span", { class: "bar-delta" }, d === 0 ? `как в ${prevName}` : `${d > 0 ? "▲" : "▼"} ${Math.abs(d)}% к ${prevName.replace(/е$/, "ю")}`);
    }
    box.append(el("div", { class: "bar" },
      el("span", { class: "bar-name" }, cat.name),
      track,
      el("b", {}, money(cat.total), el("small", {}, `${share}%`)),
      note || delta ? el("div", { class: "bar-meta" }, note, delta) : null,
    ));
  }
  // На телефоне видны первые 5 категорий, остальные — по кнопке
  if (expenses.length > 5) {
    box.classList.remove("all");
    const more = el("button", { type: "button", class: "link-btn bars-more" }, `Показать все (${expenses.length})`);
    more.addEventListener("click", () => {
      const all = box.classList.toggle("all");
      more.textContent = all ? "Свернуть" : `Показать все (${expenses.length})`;
    });
    box.append(more);
  }
}

// ---------- График расходов по дням ----------

function renderDailyChart(summary) {
  const box = $("daily-chart");
  box.replaceChildren();
  const [y, m] = summary.month.split("-").map(Number);
  const daysInMonth = new Date(y, m, 0).getDate();
  const today = todayISO();
  const isCurrent = today.slice(0, 7) === summary.month;
  const lastDay = isCurrent ? Number(today.slice(8, 10)) : today.slice(0, 7) > summary.month ? daysInMonth : 0;
  const byDay = Object.fromEntries(summary.by_day.map((d) => [Number(d.date.slice(8, 10)), d.expense]));
  const values = Array.from({ length: lastDay }, (_, i) => byDay[i + 1] || 0);
  if (!values.some((v) => v > 0)) {
    box.append(el("p", { class: "empty" }, "Расходов в этом месяце пока нет."));
    return;
  }

  // Ширина рисунка = ширина блока, чтобы на телефоне график не сжимался в полоску
  const W = Math.max(300, Math.round(box.clientWidth || 640)), H = 200, padL = 44, padR = 8, padT = 12, padB = 24;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const max = Math.max(...values);
  const step = 10 ** Math.floor(Math.log10(max));
  const top = Math.ceil(max / step) * step;
  const yOf = (v) => padT + innerH - (v / top) * innerH;
  const slot = innerW / daysInMonth;
  const barW = Math.max(2, slot - 2); // 2px зазор между столбиками
  const avg = Math.round(summary.expense_to_date / values.length);

  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "daily-svg", role: "img",
    "aria-label": `Расходы по дням, в среднем ${money(avg)} в день` });

  for (const v of [0, top / 2, top]) {
    svg.append(svgEl("line", { x1: padL, x2: W - padR, y1: yOf(v), y2: yOf(v), class: "grid" }));
    svg.append(svgEl("text", { x: padL - 6, y: yOf(v) + 4, class: "axis", "text-anchor": "end" }, fmt(v)));
  }
  const tip = el("div", { class: "chart-tip", hidden: "" });
  values.forEach((v, i) => {
    const day = i + 1;
    const x = padL + i * slot + (slot - barW) / 2;
    if (v > 0) {
      const h = Math.max(2, innerH - (yOf(v) - padT));
      const r = Math.min(4, barW / 2, h / 2);
      // скруглён только верх столбика, низ стоит на оси
      const yTop = padT + innerH - h, base = padT + innerH;
      svg.append(svgEl("path", {
        class: `bar${isCurrent && day === lastDay ? " today" : ""}`,
        d: `M${x},${base} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + barW - r} Q${x + barW},${yTop} ${x + barW},${yTop + r} V${base} Z`,
      }));
    }
    if (day === 1 || day % 5 === 0 || day === lastDay) {
      svg.append(svgEl("text", { x: padL + i * slot + slot / 2, y: H - 6, class: "axis", "text-anchor": "middle" }, day));
    }
    const hit = svgEl("rect", { x: padL + i * slot, y: padT, width: slot, height: innerH, class: "hit" });
    hit.addEventListener("mouseenter", () => {
      tip.hidden = false;
      tip.textContent = `${day} ${MONTHS_GEN[m - 1]}: ${v ? money(v) : "расходов нет"}`;
      tip.style.left = `${((padL + i * slot + slot / 2) / W) * 100}%`;
    });
    hit.addEventListener("mouseleave", () => (tip.hidden = true));
    svg.append(hit);
  });
  svg.append(svgEl("line", { x1: padL, x2: W - padR, y1: yOf(avg), y2: yOf(avg), class: "avg" }));

  box.append(
    el("p", { class: "chart-caption" }, `В среднем ${money(avg)} в день`,
      el("span", { class: "legend-avg" }, "пунктир — среднее")),
    el("div", { class: "chart-wrap" }, svg, tip),
  );
}

// ---------- Долги ----------

// Удаление долга целиком: кнопка и подтверждение прямо в карточке (без всплывающих окон браузера)
function debtRemover(debt) {
  const panel = el("div", { class: "debt-confirm", hidden: "" });
  const button = el("button", { type: "button", class: "link-btn debt-remove" }, "Удалить долг");
  const yes = el("button", { type: "button", class: "btn danger-fill" }, "Удалить");
  const no = el("button", { type: "button", class: "btn ghost" }, "Отмена");
  const note = el("span", { class: "editor-note", role: "status" });
  panel.append(
    el("p", {}, `Удалить все записи долга «${debt.person}»: дал ${money(debt.lent)}`,
      debt.repaid ? `, вернул ${money(debt.repaid)}` : "", "? Отменить это нельзя."),
    el("div", { class: "debt-confirm-actions" }, yes, no, note),
  );
  button.addEventListener("click", () => { panel.hidden = false; button.hidden = true; });
  no.addEventListener("click", () => { panel.hidden = true; button.hidden = false; });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    try {
      const result = await api(`/api/debts?person=${encodeURIComponent(debt.person)}`, { method: "DELETE" });
      showUndo(`Долг «${debt.person}» удалён`, result.items);
      await refresh();
    } catch (error) {
      note.textContent = error.message;
      yes.disabled = false;
    }
  });
  return { button, panel };
}

function closedDebtRow(debt) {
  const r = debtRemover(debt);
  return el("div", { class: "debt-closed-item" },
    el("div", { class: "debt-closed" }, el("span", {}, debt.person),
      el("span", {}, `${money(debt.lent)} — вернул полностью`, r.button)),
    r.panel);
}

function renderDebts() {
  const open = state.debts.filter((d) => d.balance > 0);
  const closed = state.debts.filter((d) => d.balance <= 0);
  const total = open.reduce((s, d) => s + d.balance, 0);
  $("debts-total").textContent = total ? money(total) : "";
  $("nav-debts-sum").textContent = total ? money(total).replace(" ₸", "") : "";
  const box = $("debts-list");
  box.replaceChildren();
  if (!open.length) {
    box.append(el("div", { class: "debts-empty" },
      el("p", {}, "Сейчас вам никто не должен."),
      el("p", { class: "muted" }, "Чтобы записать долг, напишите в поле ввода, например: «дал Айбеку в долг 5 000».")));
  }
  for (const debt of open) {
    const since = new Date(debt.since + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
    const form = el("div", { class: "repay", hidden: "" });
    const amount = el("input", { type: "number", min: "0", step: "any", value: debt.balance, "aria-label": "Сколько вернули" });
    const note = el("span", { class: "editor-note", role: "status" });
    const confirm = el("button", { type: "button", class: "btn primary" }, "Записать возврат");
    confirm.addEventListener("click", async () => {
      const value = Number(amount.value);
      if (!(value > 0)) return (note.textContent = "Укажите сумму больше нуля");
      confirm.disabled = true;
      try {
        await api("/api/transactions", { method: "POST", body: JSON.stringify({
          items: [{ date: todayISO(), amount: value, category: "repaid", counterparty: debt.person, description: "вернул долг" }],
        }) });
        setStatus(value >= debt.balance ? `${debt.person} вернул долг полностью` : `${debt.person} вернул ${money(value)}`);
        await refresh();
      } catch (error) {
        note.textContent = error.message;
        confirm.disabled = false;
      }
    });
    form.append(el("label", {}, "Сколько вернули, ₸", amount), confirm, note);
    const toggle = el("button", { type: "button", class: "btn ghost" }, "Вернул");
    toggle.addEventListener("click", () => {
      form.hidden = !form.hidden;
      toggle.textContent = form.hidden ? "Вернул" : "Отмена";
      if (!form.hidden) amount.focus();
    });
    const share = debt.lent ? Math.min(100, (debt.repaid / debt.lent) * 100) : 0;
    const remove = debtRemover(debt);
    box.append(el("div", { class: "debt" },
      el("div", { class: "debt-main" },
        el("span", { class: "debt-avatar", "aria-hidden": "true" }, debt.person.trim()[0]?.toUpperCase() || "?"),
        el("div", {}, el("b", {}, debt.person), el("div", { class: "debt-since" },
          `дал ${money(debt.lent)} · с ${since}`, debt.repaid ? ` · вернул ${money(debt.repaid)}` : "")),
        el("strong", { class: "lend" }, money(debt.balance)),
        toggle,
      ),
      debt.repaid ? el("div", { class: "debt-progress", title: `Вернул ${Math.round(share)}%` },
        el("span", { style: `width:${share.toFixed(1)}%` })) : null,
      form,
      remove.panel,
      el("div", { class: "debt-foot" }, remove.button),
    ));
  }
  if (closed.length) {
    const list = el("div", { class: "debts-closed", hidden: "" }, ...closed.map((d) =>
      closedDebtRow(d)));
    const toggle = el("button", { type: "button", class: "link-btn" }, `Закрытые долги (${closed.length})`);
    toggle.addEventListener("click", () => { list.hidden = !list.hidden; });
    box.append(el("div", { class: "debts-closed-wrap" }, toggle, list));
  }
}

// ---------- Разбор месяца ----------

function resetReview() {
  $("review-points").hidden = true;
  $("review-points").replaceChildren();
  $("review-source").textContent = "";
  $("review-hint").hidden = false;
  $("review-run").textContent = "Разобрать месяц";
}

async function runReview() {
  const button = $("review-run");
  const month = state.month;
  button.disabled = true;
  button.textContent = "Думаю…";
  try {
    const result = await api(`/api/insights?month=${month}`, { method: "POST" });
    if (month !== state.month) return;
    $("review-hint").hidden = true;
    $("review-points").replaceChildren(...result.points.map((p) => el("li", {}, p)));
    $("review-points").hidden = false;
    $("review-source").textContent = [
      result.source === "ai" ? "Сформулировал ИИ по посчитанным приложением цифрам" : "Простые выводы без ИИ",
      result.warning,
    ].filter(Boolean).join(". ");
    button.textContent = "Обновить разбор";
  } catch (error) {
    $("review-source").textContent = error.message;
    button.textContent = "Разобрать месяц";
  } finally {
    button.disabled = false;
  }
}

// ---------- Лимиты ----------

async function openLimits() {
  const current = Object.fromEntries((await api("/api/budgets")).map((b) => [b.category, b.limit]));
  const box = $("limits-items");
  box.replaceChildren();
  for (const cat of state.categories.filter((c) => c.kind === "expense")) {
    box.append(el("label", { class: "limit-row" },
      el("span", {}, cat.name),
      el("input", { type: "number", min: "0", step: "100", placeholder: "без лимита", "data-category": cat.key,
        "data-initial": current[cat.key] ?? "", value: current[cat.key] ?? "" }),
    ));
  }
  $("limits-note").textContent = "";
  $("limits").showModal();
}

async function saveLimits() {
  const inputs = [...$("limits-items").querySelectorAll("input")].filter((i) => i.value !== i.dataset.initial);
  $("limits-save").disabled = true;
  try {
    for (const input of inputs) {
      const limit = input.value === "" ? null : Number(input.value);
      await api(`/api/budgets/${input.dataset.category}`, { method: "PUT", body: JSON.stringify({ limit }) });
    }
    $("limits").close();
    await refresh();
    const warnings = limitWarnings();
    setStatus(inputs.length ? ["Лимиты сохранены", ...warnings].join(". ") : "");
  } catch (error) {
    $("limits-note").textContent = error.message;
  } finally {
    $("limits-save").disabled = false;
  }
}

// ---------- Таблица: дни × категории, как в Google Sheets ----------

function renderTable(rows) {
  const box = $("view-table");
  box.replaceChildren();
  if (!rows.length) {
    box.append(el("p", { class: "empty" }, "В этом месяце записей нет. Добавьте первую в поле выше."));
    return;
  }

  // Колонки: категории расходов, которые встречаются в этом месяце, в порядке справочника
  const expenseCats = [...new Set(rows.filter((r) => r.kind === "expense").map((r) => r.category))]
    .sort((a, b) => (state.order[a] ?? 99) - (state.order[b] ?? 99));
  const hasIncome = rows.some((r) => r.kind === "income");
  const hasLend = rows.some((r) => r.kind === "lend");
  const hasRepaid = rows.some((r) => r.kind === "repaid");
  const hasSave = rows.some((r) => r.kind === "save");
  const hasUnsave = rows.some((r) => r.kind === "unsave");

  // Суммы по дням
  const cells = new Map(); // "2026-11-04|transport" -> { total, notes[], rows[] }
  const add = (key, row) => {
    const cell = cells.get(key) || { total: 0, notes: [], rows: [] };
    cell.total += row.amount;
    cell.notes.push(`${row.counterparty || row.description || state.names[row.category]}: ${fmt(row.amount)}`);
    cell.rows.push(row);
    cells.set(key, cell);
  };
  for (const row of rows) {
    const col = row.kind === "expense" ? row.category : row.kind;
    add(`${row.date}|${col}`, row);
    if (row.kind === "expense") add(`${row.date}|_total`, row);
  }

  // Дни: весь месяц до сегодняшнего (или до последней записи)
  const [y, m] = state.month.split("-").map(Number);
  const daysInMonth = new Date(y, m, 0).getDate();
  const today = todayISO();
  const lastData = Math.max(...rows.map((r) => Number(r.date.slice(8, 10))));
  const lastDay = today.slice(0, 7) === state.month
    ? Math.max(Number(today.slice(8, 10)), lastData)
    : today.slice(0, 7) > state.month ? daysInMonth : lastData;

  // Итоги дня идут сразу после даты, чтобы не уезжать за край при большом числе категорий
  const columns = [
    { key: "_total", title: "Расходы за день", cls: "col-total" },
    hasIncome && { key: "income", title: "Доход", cls: "col-income" },
    hasLend && { key: "lend", title: "В долг", cls: "col-lend" },
    hasRepaid && { key: "repaid", title: "Вернули", cls: "col-income" },
    hasSave && { key: "save", title: "Отложил", cls: "col-lend" },
    hasUnsave && { key: "unsave", title: "Из накоплений", cls: "col-income" },
    ...expenseCats.map((key, i) => ({ key, title: state.names[key] || key, heat: true, cls: i === 0 ? "col-first-cat" : null })),
  ].filter(Boolean);

  const colMax = {};
  for (const col of columns) {
    colMax[col.key] = 0;
    for (const [key, cell] of cells) if (key.endsWith(`|${col.key}`)) colMax[col.key] = Math.max(colMax[col.key], cell.total);
  }

  const thead = el("thead", {}, el("tr", {},
    el("th", { scope: "col" }, "Дата"),
    ...columns.map((col) => el("th", { scope: "col", class: col.cls }, col.title)),
  ));

  const tbody = el("tbody");
  for (let d = 1; d <= lastDay; d++) {
    const iso = `${state.month}-${String(d).padStart(2, "0")}`;
    const date = new Date(y, m - 1, d);
    const weekday = date.toLocaleDateString("ru-RU", { weekday: "short" });
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;
    const dayRows = rows.filter((r) => r.date === iso);
    const dayLabel = date.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });
    const tr = el("tr", { class: [isWeekend && "weekend", iso === today && "today"].filter(Boolean).join(" ") || null },
      el("th", { scope: "row", class: dayRows.length ? "day-col clickable" : "day-col",
        onclick: dayRows.length ? () => openEditor(dayLabel, dayRows) : null },
        `${d}`, el("small", {}, weekday)),
    );
    for (const col of columns) {
      const cell = cells.get(`${iso}|${col.key}`);
      const td = el("td", {
        class: ["cell", col.cls, cell && "clickable"].filter(Boolean).join(" "),
        title: cell ? cell.notes.join("\n") : null,
        tabindex: cell ? "0" : null,
        onclick: cell ? () => openEditor(`${dayLabel} · ${col.title}`, cell.rows) : null,
        onkeydown: cell ? (e) => { if (e.key === "Enter") openEditor(`${dayLabel} · ${col.title}`, cell.rows); } : null,
      }, cell ? fmt(cell.total) : el("span", { class: "empty-cell" }, "·"));
      if (cell && col.heat) {
        td.dataset.heat = "";
        td.style.setProperty("--heat", (0.05 + (cell.total / colMax[col.key]) * 0.2).toFixed(3));
      }
      tr.append(td);
    }
    tbody.append(tr);
  }

  const tfoot = el("tfoot", {}, el("tr", {},
    el("td", {}, "Итого, ₸"),
    ...columns.map((col) => {
      let sum = 0;
      for (const [key, cell] of cells) if (key.endsWith(`|${col.key}`)) sum += cell.total;
      return el("td", { class: col.cls }, sum ? fmt(sum) : "");
    }),
  ));

  box.append(el("table", { class: "sheet" }, thead, tbody, tfoot));
  // Прокручиваем к сегодняшнему дню, если он в этом месяце
  const todayRow = box.querySelector("tr.today");
  if (todayRow) box.scrollTop = Math.max(0, todayRow.offsetTop - box.clientHeight / 2);
}

// ---------- Календарь ----------

// Группы для цветных точек: цвет — подсказка, название группы есть в легенде и в списке дня
const CAL_GROUPS = [
  { name: "Еда", color: "#7a1f33", cats: ["products", "vegetables", "convenience", "cafe", "nuts"] },
  { name: "Дорога", color: "#a8822e", cats: ["transport"] },
  { name: "Отдаю", color: "#c0563f", cats: ["charity", "gift"] },
  { name: "Быт и одежда", color: "#8a7a6a", cats: ["household", "laundry", "housing", "clothes"] },
  { name: "Развитие", color: "#2f5d7a", cats: ["books", "sport"] },
  { name: "Отдых", color: "#5b7a3a", cats: ["leisure"] },
  { name: "Другое", color: "#9aa8a3", cats: ["other"] },
];
const CAL_COLOR = Object.fromEntries(CAL_GROUPS.flatMap((g) => g.cats.map((c) => [c, g.color])));

// Над календарём: сегодня, в среднем в день и всего за месяц
function renderDayStats(rows) {
  const box = $("day-stats");
  const spent = rows.filter((r) => r.kind === "expense");
  const total = spent.reduce((s, r) => s + r.amount, 0);
  const [y, m] = state.month.split("-").map(Number);
  const today = todayISO();
  const isCurrent = today.startsWith(state.month);
  if (!total || today < `${state.month}-01`) { box.hidden = true; return; }
  // Среднее — по прошедшим дням месяца (для текущего месяца — по сегодняшний день)
  const days = isCurrent ? Number(today.slice(8, 10)) : new Date(y, m, 0).getDate();
  const items = [];
  if (isCurrent) items.push(["Сегодня", money(spent.filter((r) => r.date === today).reduce((s, r) => s + r.amount, 0))]);
  items.push(["В среднем в день", money(Math.round(total / days))]);
  items.push([isCurrent ? `За ${days} ${plural(days, "день", "дня", "дней")}` : "За месяц", money(total)]);
  box.replaceChildren(...items.map(([k, v]) => el("div", {}, el("dt", {}, k), el("dd", {}, v))));
  box.hidden = false;
}

function renderCalendar(rows) {
  renderDayStats(rows);
  const box = $("view-calendar");
  box.replaceChildren();
  const [y, m] = state.month.split("-").map(Number);
  const daysInMonth = new Date(y, m, 0).getDate();
  const today = todayISO();
  const iso = (d) => `${state.month}-${String(d).padStart(2, "0")}`;

  const byDay = new Map();
  for (const row of rows) {
    if (!byDay.has(row.date)) byDay.set(row.date, []);
    byDay.get(row.date).push(row);
  }
  const spentOn = (day) => (byDay.get(day) || []).filter((r) => r.kind === "expense").reduce((s, r) => s + r.amount, 0);
  const totals = [...byDay.keys()].map(spentOn);
  const max = Math.max(1, ...totals);
  const avg = totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : 0;

  // Выбранный день: тот, что выбрали раньше в этом месяце, иначе сегодня, иначе последний день с записями
  // Выбор под календарём: null — весь месяц, иначе день или неделя этого месяца
  if (state.calSel && !state.calSel.from.startsWith(state.month)) state.calSel = null;
  const sel = state.calSel;
  const select = (next) => {
    hideCalTip();
    const same = sel && next && sel.from === next.from && sel.to === next.to;
    state.calSel = same ? null : next; // повторное нажатие — обратно ко всему месяцу
    renderCalendar(state.rows);
  };

  const grid = el("div", { class: "cal", role: "grid", "aria-label": "Календарь расходов" });
  ["пн", "вт", "ср", "чт", "пт", "сб", "вс"].forEach((w, i) => grid.append(el("div", { class: `cal-wh${i >= 5 ? " we" : ""}` }, w)));
  const offset = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  for (let i = 0; i < offset; i++) grid.append(el("div", { class: "cal-d blank" }));

  for (let d = 1; d <= daysInMonth; d++) {
    const day = iso(d);
    const weekday = (offset + d - 1) % 7;
    const items = byDay.get(day) || [];
    const spent = spentOn(day);
    const future = day > today;
    const groups = CAL_GROUPS.filter((g) => items.some((r) => r.kind === "expense" && g.cats.includes(r.category)));
    const extra = items.filter((r) => r.kind !== "expense");
    const cls = ["cal-d", weekday >= 5 && "we", future && "future", day === today && "today", sel?.kind === "day" && day === sel.from && "sel",
      sel?.kind === "week" && day >= sel.from && day <= sel.to && "in-week"];
    const label = new Date(day + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "long" });
    const cell = el("button", {
      type: "button", class: cls.filter(Boolean).join(" "),
      "aria-label": `${label}: ${spent ? money(spent) : "нет расходов"}`,
      "aria-pressed": sel?.kind === "day" && day === sel.from ? "true" : "false",
      style: spent ? `--h:${(0.04 + (spent / max) * 0.2).toFixed(3)}` : null,
      onclick: () => select({ kind: "day", from: day, to: day }),
      onmouseenter: (e) => showCalTip(e.currentTarget, label, items),
      onmouseleave: hideCalTip,
      onfocus: (e) => showCalTip(e.currentTarget, label, items),
      onblur: hideCalTip,
    },
      el("span", { class: "cal-n" }, d),
      spent >= Math.max(15000, avg * 2.5) && totals.length > 3 ? el("span", { class: "cal-big" }, "крупная") : null,
      el("span", { class: "cal-t" }, spent ? fmt(spent) : (items.length ? "" : future ? "" : "—")),
      el("span", { class: "cal-dots" },
        ...groups.map((g) => el("i", { style: `background:${g.color}`, title: g.name })),
        extra.length ? el("i", { class: "ring", title: "Доход или долг" }) : null),
    );
    grid.append(cell);
  }
  const tail = (7 - ((offset + daysInMonth) % 7)) % 7;
  for (let i = 0; i < tail; i++) grid.append(el("div", { class: "cal-d blank" }));

  // Итоги по неделям (пн–вс внутри месяца)
  const weeks = [];
  let start = 1;
  for (let d = 1; d <= daysInMonth; d++) {
    if ((offset + d - 1) % 7 === 6 || d === daysInMonth) {
      const sum = Array.from({ length: d - start + 1 }, (_, i) => spentOn(iso(start + i))).reduce((a, b) => a + b, 0);
      if (iso(start) <= today) weeks.push({ from: start, to: d, sum });
      start = d + 1;
    }
  }
  const monthName = new Date(y, m - 1, 1).toLocaleDateString("ru-RU", { month: "long", day: "numeric" }).split(" ")[1];
  const weekBox = el("div", { class: "cal-weeks" }, ...weeks.map((w) => {
    const range = { kind: "week", from: iso(w.from), to: iso(w.to) };
    const active = sel?.kind === "week" && sel.from === range.from;
    const name = w.from === w.to ? `${w.from} ${monthName}` : `${w.from}–${w.to} ${monthName}`;
    return el("button", { type: "button", class: `cal-week${active ? " active" : ""}`, "aria-pressed": String(active),
      title: "Показать записи за неделю", onclick: () => select({ ...range, name }) },
      name, el("b", {}, w.sum ? money(w.sum) : "—"));
  }));

  const legend = el("div", { class: "cal-legend" }, ...CAL_GROUPS.filter((g) => g.name !== "Другое").map((g) =>
    el("span", {}, el("i", { style: `background:${g.color}` }), g.name)),
    el("span", {}, el("i", { class: "ring" }), "доход или долг"));

  box.append(grid, el("div", { class: "cal-below" },
    sel?.kind === "day"
      ? renderCalendarDay(sel.from, byDay.get(sel.from) || [])
      : renderCalendarRange(sel, rows.filter((r) => !sel || (r.date >= sel.from && r.date <= sel.to))),
    el("div", { class: "cal-aside" }, legend, weekBox)));
}

// Подсказка при наведении: на что ушли деньги в этот день
function showCalTip(cell, label, items) {
  if (!items.length || matchMedia("(hover: none)").matches) return; // на телефоне хватает списка под календарём
  let tip = $("cal-tip");
  if (!tip) {
    tip = el("div", { id: "cal-tip", class: "cal-tip", role: "tooltip" });
    document.body.append(tip);
  }
  const byCat = new Map();
  for (const r of items.filter((r) => r.kind === "expense")) byCat.set(r.category, (byCat.get(r.category) || 0) + r.amount);
  const spent = [...byCat.values()].reduce((a, b) => a + b, 0);
  const lines = [...byCat].sort((a, b) => b[1] - a[1]);
  const shown = lines.slice(0, 6);
  const rest = lines.slice(6).reduce((s, [, v]) => s + v, 0);
  const other = items.filter((r) => r.kind !== "expense");

  tip.replaceChildren(...[
    el("div", { class: "cal-tip-head" }, el("span", {}, label), spent ? el("b", {}, money(spent)) : null),
    ...shown.map(([cat, sum]) => el("div", { class: "cal-tip-row" },
      el("i", { style: `background:${CAL_COLOR[cat] || "#c9d3cc"}` }),
      el("span", {}, state.names[cat] || cat),
      el("span", { class: "cal-tip-bar" }, el("span", {
        style: `width:${Math.max(4, (sum / spent) * 100).toFixed(0)}%;background:${CAL_COLOR[cat] || "#9aa8a3"}` })),
      el("b", {}, money(sum)))),
    rest ? el("div", { class: "cal-tip-row" }, el("i"), el("span", {}, `ещё ${lines.length - 6}`), el("span"), el("b", {}, money(rest))) : null,
    ...other.map((r) => el("div", { class: "cal-tip-row extra" },
      el("i", { class: "ring" }),
      el("span", {}, kindLabel(r)),
      el("span"),
      el("b", { class: r.kind }, kindSign(r.kind) + money(r.amount)))),
  ].filter(Boolean));
  tip.hidden = false;
  const box = cell.getBoundingClientRect();
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let left = box.left + box.width / 2 - w / 2;
  left = Math.min(Math.max(8, left), window.innerWidth - w - 8);
  let top = box.top - h - 10;
  tip.classList.toggle("below", top < 8);
  if (top < 8) top = box.bottom + 10;
  tip.style.setProperty("--arrow", `${Math.min(w - 16, Math.max(16, box.left + box.width / 2 - left))}px`);
  tip.style.left = `${left + window.scrollX}px`;
  tip.style.top = `${top + window.scrollY}px`;
}

function hideCalTip() {
  const tip = $("cal-tip");
  if (tip) tip.hidden = true;
}

function plural(n, one, few, many) {
  if (n % 10 === 1 && n % 100 !== 11) return one;
  return [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;
}

function backToMonth() {
  return el("button", { type: "button", class: "link-btn cal-back",
    onclick: () => { state.calSel = null; renderCalendar(state.rows); } }, "← Весь месяц");
}

// Сводка за месяц или неделю: по категориям, как «Куда ушли деньги», но с числом записей
function renderCalendarRange(sel, items) {
  const [y, m] = state.month.split("-").map(Number);
  const monthTitle = new Date(y, m - 1, 1).toLocaleDateString("ru-RU", { month: "long" });
  const title = sel ? `Неделя ${sel.name}` : `${monthTitle[0].toUpperCase()}${monthTitle.slice(1)} целиком`;
  const expenses = items.filter((r) => r.kind === "expense");
  const spent = expenses.reduce((s, r) => s + r.amount, 0);
  const byCat = new Map();
  for (const r of expenses) {
    const c = byCat.get(r.category) || { sum: 0, count: 0 };
    c.sum += r.amount; c.count += 1;
    byCat.set(r.category, c);
  }
  const days = new Set(expenses.map((r) => r.date)).size;
  const panel = el("aside", { class: `cal-day${sel ? "" : " cal-month"}`, "aria-live": "polite" },
    el("div", { class: "cal-day-head" }, el("h3", {}, title), sel ? backToMonth() : null),
    el("p", { class: "cal-sub" }, items.length
      ? `${items.length} ${plural(items.length, "запись", "записи", "записей")}` +
        (days ? ` · в среднем ${money(Math.round(spent / days))} в день` : "")
      : "Записей нет"),
    spent ? el("p", { class: "cal-total" }, money(spent)) : null,
  );
  for (const [cat, c] of [...byCat].sort((a, b) => b[1].sum - a[1].sum)) {
    panel.append(el("div", { class: "cal-it cal-cat" },
      el("i", { style: `background:${CAL_COLOR[cat] || "#c9d3cc"}` }),
      el("span", {}, state.names[cat] || cat,
        el("small", {}, `${c.count} ${plural(c.count, "раз", "раза", "раз")} · ${Math.round((c.sum / spent) * 100)}%`),
        el("span", { class: "cal-share" }, el("span", { style: `width:${Math.max(2, (c.sum / spent) * 100).toFixed(1)}%;background:${CAL_COLOR[cat] || "#c9d3cc"}` }))),
      el("b", {}, money(c.sum)),
    ));
  }
  const flows = [
    ["income", "Доходы", "+"], ["lend", "Дал в долг", "→ "], ["repaid", "Вернули долг", "+"],
    ["save", "Отложил", "→ "], ["unsave", "Взял из накоплений", "+"],
  ].map(([kind, name, sign]) => {
    const list = items.filter((r) => r.kind === kind);
    if (!list.length) return null;
    const sum = list.reduce((s, r) => s + r.amount, 0);
    return el("div", { class: "cal-it cal-cat" }, el("i", { class: "ring" }),
      el("span", {}, name, el("small", {}, `${list.length} ${plural(list.length, "запись", "записи", "записей")}`)),
      el("b", { class: kind }, sign + money(sum)));
  }).filter(Boolean);
  if (flows.length) panel.append(el("p", { class: "cal-flows-title" }, "Кроме расходов"), ...flows);
  panel.append(el("p", { class: "cal-hint" }, "Нажмите на день или неделю, чтобы увидеть их записи."));
  return panel;
}

function renderCalendarDay(day, items) {
  const label = new Date(day + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "long" });
  const spent = items.filter((r) => r.kind === "expense").reduce((s, r) => s + r.amount, 0);
  const count = items.length;
  const word = count % 10 === 1 && count % 100 !== 11 ? "запись"
    : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100) ? "записи" : "записей";
  const panel = el("aside", { class: "cal-day", "aria-live": "polite" },
    el("div", { class: "cal-day-head" }, el("h3", {}, label), backToMonth()),
    el("p", { class: "cal-sub" }, count ? `${count} ${word}` : "Записей нет"),
    spent ? el("p", { class: "cal-total" }, money(spent)) : null,
  );
  for (const row of items) {
    const sign = kindSign(row.kind);
    panel.append(el("button", { type: "button", class: "cal-it", title: "Изменить запись", onclick: () => openEditor(label, [row]) },
      el("i", { style: `background:${CAL_COLOR[row.category] || "#c9d3cc"}` }),
      el("span", {}, row.counterparty || row.description || state.names[row.category],
        row.counterparty || (row.description && row.description.toLowerCase() !== (state.names[row.category] || "").toLowerCase())
          ? el("small", {}, state.names[row.category] || row.category) : null),
      el("b", { class: row.kind }, sign + money(row.amount)),
    ));
  }
  panel.append(el("button", { type: "button", class: "link-btn cal-add", onclick: () => {
    $("date").value = day;
    $("text").focus();
    $("text").scrollIntoView({ behavior: "smooth", block: "center" });
  } }, "+ Добавить запись на этот день"));
  return panel;
}

// ---------- Таблица для телефона: категории × недели ----------

function monthWeeks(month) {
  const [y, m] = month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const offset = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  const today = todayISO();
  const weeks = [];
  let start = 1;
  for (let d = 1; d <= days; d++) {
    if ((offset + d - 1) % 7 === 6 || d === days) {
      const from = `${month}-${String(start).padStart(2, "0")}`;
      if (from <= today) weeks.push({ from, to: `${month}-${String(d).padStart(2, "0")}`, label: start === d ? `${start}` : `${start}–${d}` });
      start = d + 1;
    }
  }
  return weeks;
}

function renderWeekTable(rows) {
  const box = $("view-weeks");
  box.replaceChildren();
  if (!rows.length) {
    box.append(el("p", { class: "empty" }, "В этом месяце записей нет."));
    return;
  }
  const weeks = monthWeeks(state.month);
  const monthGen = MONTHS_GEN[Number(state.month.slice(5, 7)) - 1];
  const expense = rows.filter((r) => r.kind === "expense");
  const totals = new Map();
  for (const r of expense) totals.set(r.category, (totals.get(r.category) || 0) + r.amount);
  const cats = [...totals.keys()].sort((a, b) => totals.get(b) - totals.get(a));
  const inWeek = (r, w) => r.date >= w.from && r.date <= w.to;
  const lines = [
    ...cats.map((c) => ({ name: state.names[c] || c, rows: expense.filter((r) => r.category === c), heat: true })),
    { name: "Всего расходов", rows: expense, cls: "wk-sum" },
    ...[["income", "Доходы"], ["lend", "Дал в долг"], ["repaid", "Вернули"], ["save", "Отложил"], ["unsave", "Из накоплений"]]
      .map(([k, name]) => ({ name, rows: rows.filter((r) => r.kind === k), cls: `wk-${k}` }))
      .filter((l) => l.rows.length),
  ];
  const max = Math.max(1, ...cats.flatMap((c) => weeks.map((w) =>
    expense.filter((r) => r.category === c && inWeek(r, w)).reduce((s, r) => s + r.amount, 0))));
  const short = (v) => (v >= 10000 ? `${(v / 1000).toFixed(v >= 100000 ? 0 : 1).replace(".", ",").replace(/,0$/, "")}к` : fmt(v));

  const table = el("table", { class: "weeks-table" },
    el("thead", {}, el("tr", {}, el("th", { scope: "col" }, monthGen[0].toUpperCase() + monthGen.slice(1) + ", дни"),
      ...weeks.map((w) => el("th", { scope: "col" }, w.label)), el("th", { scope: "col", class: "wk-total" }, "Итого"))),
  );
  const body = el("tbody");
  for (const line of lines) {
    const tr = el("tr", { class: line.cls || null }, el("th", { scope: "row" }, line.name));
    for (const w of weeks) {
      const list = line.rows.filter((r) => inWeek(r, w));
      const sum = list.reduce((s, r) => s + r.amount, 0);
      const title = `${line.name} · ${w.label} ${monthGen}`;
      const td = el("td", { class: list.length ? "clickable" : null,
        onclick: list.length ? () => openEditor(title, list) : null }, sum ? short(sum) : "");
      if (line.heat && sum) td.style.background = `rgba(122, 31, 51, ${(0.05 + (sum / max) * 0.22).toFixed(3)})`;
      tr.append(td);
    }
    const all = line.rows.reduce((s, r) => s + r.amount, 0);
    tr.append(el("td", { class: "wk-total" }, short(all)));
    body.append(tr);
  }
  table.append(body);
  box.append(table, el("p", { class: "weeks-hint" }, "Суммы по неделям месяца, «к» — тысячи. Нажмите на сумму, чтобы увидеть записи."));
}

// ---------- Окно редактирования ----------

const editor = { title: "", ids: [] };

function openEditor(title, rows) {
  editor.title = title;
  editor.ids = rows.map((r) => r.id);
  renderEditor();
  const dialog = $("editor");
  if (!dialog.open) dialog.showModal();
}

function renderEditor() {
  const rows = state.rows.filter((r) => editor.ids.includes(r.id));
  if (!rows.length) {
    $("editor").close();
    return;
  }
  $("editor-title").textContent = editor.title;
  const box = $("editor-items");
  box.replaceChildren();
  for (const row of rows) {
    const draft = { date: row.date, category: row.category, amount: row.amount, description: row.description,
      counterparty: row.counterparty || "" };
    const personField = el("label", { class: "wide" }, "Кто (кому дал или кто вернул)",
      el("input", { type: "text", value: draft.counterparty, maxlength: "100",
        onchange: (e) => (draft.counterparty = e.target.value) }));
    personField.hidden = !isPersonKind(row.category);
    const note = el("span", { class: "editor-note", role: "status" });
    const remove = el("button", { type: "button", class: "btn ghost danger" }, "Удалить");
    // Подтверждение прямо под записью: понятный вопрос и две кнопки «Да» / «Нет»
    const yes = el("button", { type: "button", class: "btn danger-fill" }, "Да, удалить");
    const no = el("button", { type: "button", class: "btn ghost" }, "Нет");
    const what = [row.description || state.names[row.category], money(row.amount)].filter(Boolean).join(", ");
    const ask = el("div", { class: "debt-confirm row-confirm", hidden: "" },
      el("p", {}, `Удалить запись «${what}»? Отменить это нельзя.`),
      el("div", { class: "debt-confirm-actions" }, yes, no));
    remove.addEventListener("click", () => {
      ask.hidden = false;
      actions.hidden = true;
      yes.focus();
    });
    no.addEventListener("click", () => {
      ask.hidden = true;
      actions.hidden = false;
    });
    yes.addEventListener("click", async () => {
      yes.disabled = true;
      try {
        await api(`/api/transactions/${row.id}`, { method: "DELETE" });
        showUndo(`Запись «${what}» удалена`, [restorable(row)]);
        await refresh();
        renderEditor();
      } catch (error) {
        ask.hidden = true;
        actions.hidden = false;
        yes.disabled = false;
        note.textContent = error.message;
      }
    });
    const save = el("button", { type: "button", class: "btn primary" }, "Сохранить");
    const actions = el("div", { class: "editor-actions" }, note, remove, save);
    save.addEventListener("click", async () => {
      if (!(draft.amount > 0)) return (note.textContent = "Сумма должна быть больше нуля");
      save.disabled = true;
      try {
        const body = { ...draft, counterparty: isPersonKind(draft.category) ? draft.counterparty : null };
        await api(`/api/transactions/${row.id}`, { method: "PATCH", body: JSON.stringify(body) });
        await refresh();
        renderEditor();
        setStatus("Изменения сохранены");
      } catch (error) {
        note.textContent = error.message;
        save.disabled = false;
      }
    });
    box.append(el("div", { class: "editor-item" },
      el("div", { class: "editor-fields" },
        el("label", {}, "Дата", el("input", { type: "date", value: row.date, onchange: (e) => (draft.date = e.target.value) })),
        el("label", {}, "Категория", categorySelect(row.category, (v) => {
          draft.category = v;
          personField.hidden = !isPersonKind(v);
        })),
        el("label", {}, "Сумма, ₸", el("input", { type: "number", min: "0", step: "any", value: row.amount,
          onchange: (e) => (draft.amount = Number(e.target.value)) })),
        el("label", { class: "wide" }, "Описание", el("input", { type: "text", value: row.description, maxlength: "300",
          onchange: (e) => (draft.description = e.target.value) })),
        personField,
      ),
      actions,
      ask,
    ));
  }
}

// ---------- Обзор года ----------

const MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

async function loadYear() {
  const year = state.year || Number(state.month.slice(0, 4));
  state.year = year;
  $("year-label").textContent = year;
  try {
    const data = await api(`/api/year?year=${year}`);
    if (data.year !== state.year) return;
    renderYear(data);
  } catch (error) {
    $("year-body").replaceChildren(el("p", { class: "muted" }, error.message));
  }
}

function renderYear(data) {
  const body = $("year-body");
  const thisYear = new Date().getFullYear();
  $("year-next").disabled = data.year >= thisYear;
  $("year-prev").disabled = data.first_year ? data.year <= data.first_year : true;
  const active = data.months.filter((m) => m.expense || m.income || m.saved);
  if (!active.length) {
    body.replaceChildren(el("p", { class: "muted" }, `За ${data.year} год записей нет.`));
    return;
  }
  const sum = (key) => data.months.reduce((s, m) => s + m[key], 0);
  const income = sum("income"), expense = sum("expense"), saved = sum("saved");
  const withExpense = data.months.filter((m) => m.expense > 0);
  // Текущий месяц ещё не закончился — в «самый экономный» его не берём
  const nowMonth = todayISO().slice(0, 7);
  const finished = withExpense.filter((m) => m.month < nowMonth);
  const maxM = withExpense.reduce((a, b) => (b.expense > a.expense ? b : a), withExpense[0]);
  const minM = finished.length > 1 ? finished.reduce((a, b) => (b.expense < a.expense ? b : a), finished[0]) : null;
  const avg = withExpense.length ? expense / withExpense.length : 0;
  const change = data.prev_expense ? Math.round(((expense - data.prev_expense) / data.prev_expense) * 100) : null;

  const tiles = el("dl", { class: "year-tiles" },
    el("div", {}, el("dt", {}, "Доходы"), el("dd", { class: "income" }, money(income))),
    el("div", {}, el("dt", {}, "Расходы"), el("dd", {}, money(expense)),
      change !== null ? el("small", {}, `${change > 0 ? "▲" : "▼"} ${Math.abs(change)}% к ${data.year - 1}`) : null),
    el("div", {}, el("dt", {}, "Отложено"), el("dd", { class: "save" }, money(saved))),
    el("div", {}, el("dt", {}, "В среднем в месяц"), el("dd", {}, money(Math.round(avg)))),
  );

  const max = Math.max(1, ...data.months.map((m) => Math.max(m.expense, m.income)));
  const first = data.months.findIndex((m) => m.expense || m.income || m.saved);
  const last = data.months.length - 1 - [...data.months].reverse().findIndex((m) => m.expense || m.income || m.saved);
  const list = el("div", { class: "year-months", role: "list" });
  for (const m of data.months.slice(first, last + 1)) {
    const idx = Number(m.month.slice(5, 7)) - 1;
    const tag = m === maxM && withExpense.length > 1 ? el("span", { class: "ym-tag hot" }, "больше всего трат")
      : m === minM ? el("span", { class: "ym-tag cool" }, "самый экономный") : null;
    const row = el("button", { type: "button", class: "ym-row", role: "listitem",
      title: `Открыть ${MONTHS_PREP[idx]} в календаре`,
      onclick: () => { setMonth(m.month); setScreen("home"); } },
      el("span", { class: "ym-name" }, MONTHS_SHORT[idx]),
      el("span", { class: "ym-bars" },
        el("span", { class: "ym-bar expense", style: `width:${((m.expense / max) * 100).toFixed(1)}%` }),
        el("span", { class: "ym-bar income", style: `width:${((m.income / max) * 100).toFixed(1)}%` })),
      el("span", { class: "ym-nums" },
        el("b", {}, m.expense ? money(m.expense) : "—"),
        el("small", {}, [m.income ? `+${money(m.income)}` : "", m.saved ? `отложил ${money(m.saved)}` : ""].filter(Boolean).join(" · ")),
        tag),
    );
    list.append(row);
  }
  const legend = el("p", { class: "ym-legend" },
    el("span", {}, el("i", { class: "expense" }), "расходы"), el("span", {}, el("i", { class: "income" }), "доходы"),
    "Нажмите на месяц, чтобы открыть его в календаре.");

  const top = data.categories.slice(0, 6);
  const cats = el("div", { class: "year-cats" }, el("h3", {}, "Куда ушли деньги за год"),
    ...top.map((c) => {
      const delta = c.prev_total ? Math.round(((c.total - c.prev_total) / c.prev_total) * 100) : null;
      return el("div", { class: "yc-row" },
        el("span", {}, c.name),
        el("span", { class: "yc-share" }, el("span", { style: `width:${((c.total / expense) * 100).toFixed(1)}%` })),
        el("b", {}, money(c.total)),
        el("small", {}, `${Math.round((c.total / expense) * 100)}%` + (delta !== null ? ` · ${delta > 0 ? "▲" : "▼"}${Math.abs(delta)}%` : "")));
    }));

  body.replaceChildren(tiles, el("div", { class: "year-grid" }, el("div", {}, list, legend), cats));
}

// ---------- «Вернуть» после удаления ----------

let toastTimer = null;
let toastUndo = null;

function showUndo(text, items) {
  toastUndo = items;
  $("toast-text").textContent = text;
  $("toast-undo").hidden = !items?.length;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 10000);
}

function hideToast() {
  $("toast").hidden = true;
  toastUndo = null;
}

async function undoDelete() {
  const items = toastUndo;
  if (!items) return;
  hideToast();
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify({ items }) });
    setStatus(items.length > 1 ? `Вернул ${items.length} записи` : "Запись возвращена");
    await refresh();
    if (document.body.dataset.screen === "stats") loadYear();
    if ($("savings-dialog").open) loadSavings();
  } catch (error) {
    setStatus(error.message, true);
  }
}

const restorable = (row) => ({ date: row.date, amount: row.amount, category: row.category,
  description: row.description || "", counterparty: row.counterparty || null });

// ---------- Накопления: история, «взял» и удаление ошибочных записей ----------

function openSavings() {
  $("sv-date").value = todayISO();
  $("sv-status").textContent = "";
  $("savings-dialog").showModal();
  loadSavings();
}

async function loadSavings() {
  try {
    renderSavings(await api("/api/savings"));
  } catch (error) {
    $("sv-list").replaceChildren(el("li", { class: "sv-empty" }, error.message));
  }
}

function renderSavings(data) {
  $("sv-total").textContent = money(data.total);
  $("sv-total").classList.toggle("neg", data.total < 0);
  const list = $("sv-list");
  if (!data.items.length) {
    list.replaceChildren(el("li", { class: "sv-empty" }, "Пока пусто. Напишите «отложил 20 000» — запись появится здесь."));
    return;
  }
  list.replaceChildren(...data.items.map(savingsRow));
}

function savingsRow(row) {
  const out = row.kind === "unsave";
  const date = new Date(`${row.date}T00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
  const what = row.description || (out ? "Взял из накоплений" : "Отложил");
  const yes = el("button", { type: "button", class: "btn danger-fill" }, "Да, удалить");
  const no = el("button", { type: "button", class: "btn ghost" }, "Нет");
  const ask = el("div", { class: "debt-confirm row-confirm", hidden: "" },
    el("p", {}, `Удалить запись «${what}, ${money(row.amount)}»?`),
    el("div", { class: "debt-confirm-actions" }, yes, no));
  const remove = el("button", { type: "button", class: "icon-btn", "aria-label": `Удалить запись «${what}»`, title: "Удалить" }, "×");
  const item = el("li", { class: "sv-row" },
    el("div", { class: "sv-main" },
      el("span", { class: "sv-date" }, date),
      el("span", { class: "sv-what" }, el("b", {}, out ? "Взял" : "Отложил"), row.description ? ` · ${row.description}` : ""),
      el("span", { class: `sv-amount ${out ? "out" : "in"}` }, `${out ? "−" : "+"}${money(row.amount)}`),
      remove),
    ask);
  remove.addEventListener("click", () => { ask.hidden = false; yes.focus(); });
  no.addEventListener("click", () => { ask.hidden = true; });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    try {
      await api(`/api/transactions/${row.id}`, { method: "DELETE" });
      showUndo(`Запись «${what}» удалена`, [restorable(row)]);
      await Promise.all([loadSavings(), refresh()]);
    } catch (error) {
      yes.disabled = false;
      ask.querySelector("p").textContent = error.message;
    }
  });
  return item;
}

async function saveSavings(event) {
  event.preventDefault();
  const out = event.submitter?.value !== "in";
  const amount = Number($("sv-amount").value.replace(/\s/g, "").replace(",", "."));
  const status = $("sv-status");
  if (!(amount > 0)) {
    status.textContent = "Введите сумму больше нуля";
    $("sv-amount").focus();
    return;
  }
  const buttons = $("sv-form").querySelectorAll("button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    await api("/api/transactions", { method: "POST", body: JSON.stringify({ items: [{
      date: $("sv-date").value || todayISO(), amount, category: out ? "savings_out" : "savings",
      description: $("sv-note").value.trim(),
    }] }) });
    $("sv-amount").value = "";
    $("sv-note").value = "";
    status.textContent = "";
    await Promise.all([loadSavings(), refresh()]);
  } catch (error) {
    status.textContent = error.message;
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

// ---------- Экраны и кнопка «Назад» ----------
// У каждого экрана свой адрес (#calendar, #table, #stats, #debts) в истории браузера:
// кнопка или жест «назад» возвращает на прошлый экран, а не уводит с сайта.
const SCREEN_HASH = { home: "#calendar", table: "#table", stats: "#stats", debts: "#debts" };
const screenFromHash = () => Object.keys(SCREEN_HASH).find((k) => SCREEN_HASH[k] === location.hash) || null;

function setView(view) {
  setScreen(view === "table" ? "table" : "home");
}

// На телефоне каждая вкладка внизу — отдельный экран (на компьютере всё на одной странице)
const isPhone = () => matchMedia("(max-width: 720px)").matches;

let screenSteps = 0; // сколько раз мы сами шагнули вперёд по экранам — столько можно вернуться назад
let closingDialog = false;

function setScreen(screen, history = "push") {
  const changed = document.body.dataset.screen !== screen;
  const view = screen === "table" ? "table" : "calendar";
  if (screen === "home" || screen === "table") {
    state.view = view;
    for (const name of ["table", "calendar"]) $(`view-${name}`).hidden = view !== name;
  }
  document.body.dataset.screen = screen;
  if (screen === "stats" && changed) loadYear();
  const tabs = { "tab-calendar": "home", "tab-table": "table", "nav-review": "stats", "nav-debts": "debts" };
  for (const [id, name] of Object.entries(tabs)) $(id).setAttribute("aria-selected", screen === name ? "true" : "false");
  const hash = SCREEN_HASH[screen];
  if (history === "push" && location.hash !== hash) {
    window.history.pushState({ screen }, "", hash);
    screenSteps += 1;
  }
  if (history === "replace") window.history.replaceState({ screen }, "", hash);
  if (changed) window.scrollTo({ top: 0, behavior: "instant" });
}

function goBack() {
  // Если до этого был наш экран — шаг назад по истории, иначе просто на главную
  if (screenSteps > 0) window.history.back();
  else setScreen("home", "replace");
}

window.addEventListener("popstate", () => {
  if (closingDialog) { closingDialog = false; return; } // это мы сами убрали запись открытого окна
  const open = document.querySelector("dialog[open]");
  if (open) { open.close(); return; } // «назад» сначала закрывает открытое окно
  screenSteps = Math.max(0, screenSteps - 1);
  setScreen(screenFromHash() || "home", "none");
});

// Окна (редактирование, аккаунт, лимиты) тоже закрываются кнопкой «назад»
const showModalOriginal = HTMLDialogElement.prototype.showModal;
HTMLDialogElement.prototype.showModal = function () {
  window.history.pushState({ screen: document.body.dataset.screen, dialog: true }, "", location.hash);
  this.addEventListener("close", () => {
    if (window.history.state?.dialog) { closingDialog = true; window.history.back(); }
  }, { once: true });
  return showModalOriginal.call(this);
};

async function refresh() {
  const month = state.month;
  try {
    const [summary, rows, debts] = await Promise.all([
      api(`/api/summary?month=${month}`),
      api(`/api/transactions?month=${month}`),
      api("/api/debts"),
    ]);
    state.debts = debts;
    renderDebts();

    if (month !== state.month) return; // пока грузили, переключили месяц
    state.rows = rows;
    renderSummary(summary);
    renderTable(rows);
    renderWeekTable(rows);
    renderCalendar(rows);
    if (document.body.dataset.screen === "stats") loadYear();
  } catch (error) {
    setStatus(error.message, true);
  }
}

// ---------- Загрузка из Excel (или CSV) ----------

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("Не получилось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

async function importFile(event) {
  const file = event.target.files[0];
  event.target.value = ""; // чтобы можно было выбрать тот же файл ещё раз
  if (!file) return;
  setStatus(`Загружаю ${file.name}…`);
  try {
    let body;
    if (/\.csv$/i.test(file.name)) {
      body = { csv: await file.text() };
    } else {
      if (file.size > 5 * 1024 * 1024) throw new Error("Файл больше 5 МБ — разбейте его на части");
      body = { xlsx: await toBase64(file) };
    }
    const result = await api("/api/import", { method: "POST", body: JSON.stringify(body) });
    setStatus(`Загружено записей: ${result.imported}`);
    const month = result.months[result.months.length - 1];
    if (month && month !== state.month) setMonth(month);
    else await refresh();
  } catch (error) {
    setStatus(error.message, true);
  }
}

// ---------- Голосовой ввод (Chrome, Edge, Safari) ----------

// Два способа голосового ввода:
// 1) основной — записываем звук и распознаём на сервере (Whisper): точнее с суммами, именами
//    и казахскими словами;
// 2) запасной — встроенное распознавание браузера, если сервер или запись звука недоступны.
function setupVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  if (!Recognition && !canRecord) return;
  const button = $("voice");
  const text = $("text");
  button.hidden = false;

  let mode = null;        // "server" | "browser" — что сейчас слушает
  let before = "";        // текст в поле до начала записи
  const join = (...parts) => parts.map((p) => p.trim()).filter(Boolean).join(", ");
  const setButton = (on) => {
    button.classList.toggle("listening", on);
    button.textContent = on ? "■ Остановить" : "Голосом";
    button.setAttribute("aria-pressed", String(on));
  };
  const showText = (value) => {
    text.value = value;
    text.dispatchEvent(new Event("input")); // поле подстраивает высоту
  };

  // ----- 1. Запись и распознавание на сервере -----
  let recorder = null;
  let stream = null;
  let chunks = [];
  let limitTimer = null;

  const pickMime = () => ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
    .find((m) => window.MediaRecorder.isTypeSupported?.(m)) || "";

  async function startServer() {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mimeType = pickMime();
    recorder = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 48000 } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = sendToServer;
    recorder.start();
    mode = "server";
    setButton(true);
    setStatus("Слушаю… Говорите сколько нужно, потом нажмите «Остановить»");
    limitTimer = setTimeout(() => recorder?.state === "recording" && recorder.stop(), 3 * 60 * 1000);
  }

  async function sendToServer() {
    clearTimeout(limitTimer);
    stream?.getTracks().forEach((t) => t.stop());
    mode = null;
    setButton(false);
    const type = (recorder.mimeType || "audio/webm");
    const blob = new Blob(chunks, { type });
    if (blob.size < 1000) return setStatus("Ничего не записалось — попробуйте ещё раз", true);
    button.disabled = true;
    button.textContent = "Распознаю…";
    setStatus("Распознаю речь…");
    try {
      const response = await fetch("/api/transcribe", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": type }, body: blob,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Не получилось распознать речь");
      showText(join(before, data.text));
      setStatus("");
      await parseText(); // сразу разбираем: в предпросмотре всё можно поправить
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Голосом";
    }
  }

  // ----- 2. Запасной вариант: распознавание браузера -----
  // Слушаем, пока человек сам не нажмёт «Остановить»; если браузер сам прервал — перезапускаем.
  let recognition = null;
  let heard = "";

  function startBrowserSession() {
    recognition = new Recognition();
    recognition.lang = "ru-RU";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const piece = event.results[i][0].transcript;
        if (event.results[i].isFinal) heard = join(heard, piece);
        else interim += piece;
      }
      showText(join(before, heard, interim));
    };
    recognition.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      mode = null;
      setStatus(event.error === "not-allowed"
        ? "Разрешите доступ к микрофону в настройках браузера"
        : "Голосовой ввод не сработал: " + event.error, true);
    };
    recognition.onend = () => {
      if (mode === "browser") {
        try { startBrowserSession(); return; } catch (_) { mode = null; }
      }
      showText(join(before, heard));
      setButton(false);
      setStatus(heard ? "Готово — проверьте текст и нажмите «Разобрать»" : "");
      if (heard) text.focus();
    };
    recognition.start();
  }

  function startBrowser() {
    heard = "";
    mode = "browser";
    setButton(true);
    setStatus("Слушаю… Говорите сколько нужно, потом нажмите «Остановить»");
    startBrowserSession();
  }

  button.addEventListener("click", async () => {
    if (mode === "server") return recorder?.stop();
    if (mode === "browser") { mode = null; return recognition?.stop(); }
    before = text.value;
    try {
      if (state.sttEnabled && canRecord) await startServer();
      else if (Recognition) startBrowser();
      else setStatus("Голосовой ввод в этом браузере недоступен", true);
    } catch (error) {
      mode = null;
      setButton(false);
      stream?.getTracks().forEach((t) => t.stop());
      setStatus(error.name === "NotAllowedError"
        ? "Разрешите доступ к микрофону в настройках браузера"
        : error.message, true);
    }
  });
}


// ---------- Вход и регистрация ----------

function showAuth() {
  state.user = null;
  $("app").hidden = true;
  $("hero").hidden = true;
  $("intro").hidden = false;
  requestAnimationFrame(drawGuilloche);
  document.querySelector(".month").hidden = true;
  $("rail-nav").hidden = true;
  $("account").hidden = true;
  $("auth").hidden = false;
  $("auth-email").focus();
}

function showApp(user) {
  state.user = user;
  $("auth").hidden = true;
  $("app").hidden = false;
  $("hero").hidden = false;
  $("intro").hidden = true;
  document.querySelector(".month").hidden = false;
  $("rail-nav").hidden = false;
  $("account").hidden = false;
  $("user-email").textContent = user.email;
  const isDemo = user.email === "demo@finance.demo";
  $("demo-banner").hidden = !isDemo;
  // В демо поле уже заполнено примером — остаётся нажать «Разобрать»
  if (isDemo && !$("text").value) $("text").value = "кофе 900, такси до универа 1 200, друг вернул 5 000";
  requestAnimationFrame(drawGuilloche);
  setMonth(state.month || todayISO().slice(0, 7));
}

function setAuthMode(mode) {
  state.authMode = mode;
  const isLogin = mode === "login";
  $("auth-title").textContent = isLogin ? "Вход" : "Регистрация";
  $("auth-submit").textContent = isLogin ? "Войти" : "Создать аккаунт";
  $("auth-switch-text").textContent = isLogin ? "Нет аккаунта?" : "Уже есть аккаунт?";
  $("auth-switch").textContent = isLogin ? "Зарегистрироваться" : "Войти";
  $("auth-password").autocomplete = isLogin ? "current-password" : "new-password";
  $("auth-hint").hidden = isLogin;
  $("auth-error").textContent = "";
}

async function submitAuth(event) {
  event.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  if (!email || !password) return ($("auth-error").textContent = "Введите email и пароль");
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return ($("auth-error").textContent = "Нужен email, например karasai@gmail.com");
  }
  if (state.authMode === "register" && password.length < 8) {
    return ($("auth-error").textContent = "Пароль должен быть не короче 8 символов");
  }
  $("auth-submit").disabled = true;
  $("auth-error").textContent = "";
  try {
    const result = await api(`/api/auth/${state.authMode === "login" ? "login" : "register"}`, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    $("auth-password").value = "";
    showApp(result.user);
  } catch (error) {
    $("auth-error").textContent = error.message;
  } finally {
    $("auth-submit").disabled = false;
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* всё равно выходим */ }
  state.rows = [];
  state.preview = [];
  renderPreview();
  setStatus("");
  setAuthMode("login");
  showAuth();
}

// ---------- Аккаунт: смена пароля и удаление ----------

function openAccount() {
  for (const id of ["pw-current", "pw-new", "pw-repeat", "del-password"]) $(id).value = "";
  $("account-email").textContent = state.user?.email || "";
  $("account-install").hidden = $("install").hidden;
  $("del-confirm").checked = false;
  $("del-submit").disabled = true;
  for (const id of ["pw-note", "del-note"]) {
    $(id).textContent = "";
    $(id).classList.remove("ok");
  }
  $("account-dialog").showModal();
}

async function changePassword(event) {
  event.preventDefault();
  const note = $("pw-note");
  note.classList.remove("ok");
  const current = $("pw-current").value;
  const fresh = $("pw-new").value;
  if (!current || !fresh) return (note.textContent = "Заполните все поля");
  if (fresh.length < 8) return (note.textContent = "Новый пароль — не короче 8 символов");
  if (fresh !== $("pw-repeat").value) return (note.textContent = "Пароли не совпадают");
  $("pw-submit").disabled = true;
  note.textContent = "";
  try {
    await api("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: fresh }),
    });
    for (const id of ["pw-current", "pw-new", "pw-repeat"]) $(id).value = "";
    note.textContent = "Пароль изменён";
    note.classList.add("ok");
  } catch (error) {
    note.textContent = error.message;
  } finally {
    $("pw-submit").disabled = false;
  }
}

async function deleteAccount(event) {
  event.preventDefault();
  const note = $("del-note");
  const password = $("del-password").value;
  if (!password) return (note.textContent = "Введите пароль");
  if (!$("del-confirm").checked) return (note.textContent = "Поставьте галочку подтверждения");
  $("del-submit").disabled = true;
  note.textContent = "";
  try {
    await api("/api/auth/account", { method: "DELETE", body: JSON.stringify({ password }) });
    $("account-dialog").close();
    state.rows = [];
    state.preview = [];
    renderPreview();
    setAuthMode("register");
    showAuth();
    $("auth-error").textContent = "Аккаунт удалён";
  } catch (error) {
    note.textContent = error.message;
    $("del-submit").disabled = !$("del-confirm").checked;
  }
}

// ---------- Узор купюры ----------

// Гильош — переплетение синусоид, как на банкнотах. Рисуется под ширину шапки.
function drawGuilloche() {
  const svg = $("guilloche");
  const W = Math.max(200, Math.round(svg.clientWidth || 300));
  const H = Math.max(200, Math.round(svg.clientHeight || 900));
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const tall = H > W * 1.4; // боковая панель — линии идут сверху вниз, мобильная шапка — слева направо
  const [len, across] = tall ? [H, W] : [W, H];
  let paths = "";
  for (let k = 0; k < 18; k++) {
    let d = "";
    for (let t = 0; t <= len; t += 6) {
      const v = across * 0.5 + Math.sin(t / 110 + k * 0.35) * (across * 0.3 + k * 2) + Math.sin(t / 29 + k) * 5;
      const [x, y] = tall ? [v, t] : [t, v];
      d += `${t ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }
    paths += `<path d="${d}" fill="none" stroke="${k % 3 ? "#8a3a4e" : "#C9A15A"}" stroke-width="0.6"/>`;
  }
  svg.innerHTML = paths;
}

function drawRosette() {
  let paths = "";
  for (let k = 0; k < 36; k++) {
    let d = "";
    for (let t = 0; t <= 360; t += 3) {
      const a = (t * Math.PI) / 180;
      const r = 60 + 22 * Math.sin(7 * a + k * 0.17);
      d += `${t ? "L" : "M"}${(100 + r * Math.cos(a + k * 0.05)).toFixed(1)},${(100 + r * Math.sin(a + k * 0.05)).toFixed(1)}`;
    }
    paths += `<path d="${d}" fill="none" stroke="#D8B46A" stroke-width="0.5" opacity=".8"/>`;
  }
  $("rosette").innerHTML = paths +
    '<circle cx="100" cy="100" r="33" fill="#4a1524" stroke="#DCB866" stroke-width="1"/>' +
    '<text x="100" y="109" text-anchor="middle" font-family="Playfair Display, Georgia, serif" font-size="30" font-weight="700" fill="#F6ECE1">₸</text>';
}

// ---------- Установка как приложение ----------

let installPrompt = null;

function setupInstall() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* без service worker сайт тоже работает */ });
  }
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const button = $("install");
  button.hidden = Boolean(standalone);
  // Chrome и Android сами предлагают установку — перехватываем, чтобы показать по нашей кнопке
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
  });
  window.addEventListener("appinstalled", () => {
    button.hidden = true;
    setStatus("Приложение установлено — ищите иконку «Финансы» на главном экране");
  });
  button.addEventListener("click", async () => {
    if (installPrompt) {
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
    } else {
      $("install-help").showModal(); // iPhone и браузеры без системного окна установки
    }
  });
  $("install-close").addEventListener("click", () => $("install-help").close());
}

// ---------- Запуск ----------

async function init() {
  $("date").value = todayISO();
  $("parse").addEventListener("click", parseText);
  $("save").addEventListener("click", savePreview);
  $("cancel").addEventListener("click", () => { state.preview = []; renderPreview(); setStatus(""); });
  $("prev-month").addEventListener("click", () => setMonth(shiftMonth(state.month, -1)));
  $("next-month").addEventListener("click", () => setMonth(shiftMonth(state.month, 1)));
  $("tab-table").addEventListener("click", () => setView("table"));
  $("tab-calendar").addEventListener("click", () => setView("calendar"));
  $("back").addEventListener("click", goBack);
  $("toast-undo").addEventListener("click", undoDelete);
  $("year-prev").addEventListener("click", () => { state.year -= 1; loadYear(); });
  $("year-next").addEventListener("click", () => { state.year += 1; loadYear(); });
  const goTo = (node) => node.scrollIntoView({ behavior: "smooth", block: "start" });
  $("nav-review").addEventListener("click", () => setScreen("stats"));
  $("fab").addEventListener("click", () => {
    setView("calendar");
    $("text").focus();
  });
  $("nav-debts").addEventListener("click", () => setScreen("debts"));
  $("nav-account").addEventListener("click", openAccount);
  $("account-logout").addEventListener("click", () => { $("account-dialog").close(); logout(); });
  $("account-install").addEventListener("click", () => { $("account-dialog").close(); $("install").click(); });

  const grow = () => {
    const t = $("text");
    t.style.height = "auto";
    t.style.height = `${t.scrollHeight}px`;
  };
  $("text").addEventListener("input", grow);
  $("text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) parseText();
  });
  setupVoice();
  setupInstall();
  drawRosette();
  drawGuilloche();
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      drawGuilloche();
      if (state.summary) renderDailyChart(state.summary);
    }, 150);
  });
  // При входе — календарь; если в адресе уже есть экран (обновили страницу) — он
  setScreen(screenFromHash() || "home", "replace");

  $("auth-form").addEventListener("submit", submitAuth);
  $("auth-demo").addEventListener("click", async () => {
    $("auth-demo").disabled = true;
    $("auth-error").textContent = "";
    try {
      showApp((await api("/api/auth/demo", { method: "POST" })).user);
    } catch (error) {
      $("auth-error").textContent = error.message;
    } finally {
      $("auth-demo").disabled = false;
    }
  });
  $("demo-close").addEventListener("click", () => ($("demo-banner").hidden = true));
  $("demo-signup").addEventListener("click", async () => {
    await logout();
    $("text").value = "";
    setAuthMode("register");
  });
  $("auth-switch").addEventListener("click", () => setAuthMode(state.authMode === "login" ? "register" : "login"));
  $("logout").addEventListener("click", logout);
  $("open-account").addEventListener("click", openAccount);
  $("account-close").addEventListener("click", () => $("account-dialog").close());
  $("saved-box").addEventListener("click", openSavings);
  $("saved-box").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSavings(); }
  });
  $("savings-open").addEventListener("click", openSavings);
  $("sv-close").addEventListener("click", () => $("savings-dialog").close());
  $("sv-form").addEventListener("submit", saveSavings);
  $("password-form").addEventListener("submit", changePassword);
  $("delete-form").addEventListener("submit", deleteAccount);
  $("del-confirm").addEventListener("change", (e) => ($("del-submit").disabled = !e.target.checked));
  $("import").addEventListener("click", () => $("import-file").click());
  $("editor-close").addEventListener("click", () => $("editor").close());
  $("open-limits").addEventListener("click", () => openLimits().catch((e) => setStatus(e.message, true)));
  $("limits-close").addEventListener("click", () => $("limits").close());
  $("limits-save").addEventListener("click", saveLimits);
  $("review-run").addEventListener("click", runReview);
  $("editor").addEventListener("click", (e) => { if (e.target === $("editor")) $("editor").close(); });
  $("import-file").addEventListener("change", importFile);
  state.month = todayISO().slice(0, 7);

  const [data, health] = await Promise.all([api("/api/categories"), api("/api/health")]);
  state.categories = data.categories;
  state.names = Object.fromEntries(data.categories.map((c) => [c.key, c.name]));
  state.order = Object.fromEntries(data.categories.map((c, i) => [c.key, i]));
  state.kinds = Object.fromEntries(data.categories.map((c) => [c.key, c.kind]));
  state.sttEnabled = Boolean(health.stt_enabled);
  $("ai-note").textContent = health.ai_enabled
    ? ""
    : "ИИ не подключён: работает простой разбор. Пишите «категория сумма» через запятую.";

  try {
    showApp(await api("/api/auth/me"));
  } catch (_) {
    showAuth();
  }
}

init().catch((error) => setStatus(error.message, true));
