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
  $("export").href = `/api/export.csv?month=${month}`;
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
  const box = $("compare");
  const days = summary.compare_days;
  if (!summary.expense_to_date && !summary.prev_expense) return (box.textContent = "");
  const now = periodLabel(summary.month, days);
  const before = periodLabel(summary.prev_month, days);
  if (!summary.prev_expense) {
    box.textContent = `Расходы ${now}: ${money(summary.expense_to_date)}. ${before[0].toUpperCase()}${before.slice(1)} записей нет — сравнивать не с чем.`;
    return;
  }
  const diff = summary.expense_to_date - summary.prev_expense;
  const pct = Math.round(Math.abs(diff) / summary.prev_expense * 100);
  const verdict = pct === 0 ? "столько же, сколько" : `на ${pct}% ${diff > 0 ? "больше" : "меньше"}, чем`;
  box.replaceChildren(
    `Расходы ${now}: `, el("b", {}, money(summary.expense_to_date)),
    ` — ${verdict} ${before} (${money(summary.prev_expense)}).`,
  );
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
  $("sum-income").textContent = money(summary.income);
  $("sum-expense").textContent = money(summary.expense);
  $("sum-lent").textContent = money(summary.lent);
  $("sum-repaid").textContent = money(summary.repaid);
  $("repaid-box").hidden = !summary.repaid;
  $("sum-balance").textContent = money(summary.balance);
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
      const mark = el("span", { class: "bar-limit", title: `Лимит ${money(cat.limit)}` });
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

function renderDebts() {
  const open = state.debts.filter((d) => d.balance > 0);
  $("debts").hidden = open.length === 0;
  $("debts-total").textContent = money(open.reduce((s, d) => s + d.balance, 0));
  const box = $("debts-list");
  box.replaceChildren();
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
    box.append(el("div", { class: "debt" },
      el("div", { class: "debt-main" },
        el("div", {}, el("b", {}, debt.person), el("div", { class: "debt-since" },
          `с ${since}`, debt.repaid ? `, уже вернул ${money(debt.repaid)}` : "")),
        el("strong", { class: "lend" }, money(debt.balance)),
        toggle,
      ),
      form,
    ));
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

// ---------- Список ----------

function renderList(rows) {
  const box = $("view-list");
  box.replaceChildren();
  if (!rows.length) {
    box.append(el("p", { class: "empty" }, "В этом месяце записей нет. Добавьте первую в поле выше."));
    return;
  }
  const byDay = new Map();
  for (const row of rows) {
    if (!byDay.has(row.date)) byDay.set(row.date, []);
    byDay.get(row.date).push(row);
  }
  for (const [day, items] of byDay) {
    const spent = items.filter((r) => r.kind === "expense").reduce((s, r) => s + r.amount, 0);
    const label = new Date(day + "T00:00").toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
    const group = el("div", { class: "day" },
      el("div", { class: "day-head" }, el("span", {}, label), el("span", {}, spent ? "расходы " + money(spent) : "")),
    );
    for (const row of items) {
      const sign = row.kind === "income" || row.kind === "repaid" ? "+" : "−";
      group.append(el("div", { class: "tx" },
        el("div", {},
          el("div", {}, row.description || state.names[row.category]),
          el("div", { class: "tx-cat" }, state.names[row.category] || row.category,
            row.counterparty ? ` · ${row.counterparty}` : ""),
        ),
        el("span", { class: `tx-amount ${row.kind}` }, sign + money(row.amount)),
        el("button", { type: "button", class: "icon-btn edit", title: "Изменить запись", "aria-label": "Изменить запись",
          onclick: () => openEditor(label, [row]) }, "✎"),
      ));
    }
    box.append(group);
  }
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
    remove.addEventListener("click", async () => {
      if (remove.dataset.armed !== "1") {
        remove.dataset.armed = "1";
        remove.textContent = "Точно удалить?";
        return;
      }
      try {
        await api(`/api/transactions/${row.id}`, { method: "DELETE" });
        setStatus("Запись удалена");
        await refresh();
        renderEditor();
      } catch (error) {
        note.textContent = error.message;
      }
    });
    const save = el("button", { type: "button", class: "btn primary" }, "Сохранить");
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
      el("div", { class: "editor-actions" }, note, remove, save),
    ));
  }
}

function setView(view) {
  state.view = view;
  storage.set("view", view);
  $("tab-table").setAttribute("aria-selected", view === "table");
  $("tab-list").setAttribute("aria-selected", view === "list");
  $("view-table").hidden = view !== "table";
  $("view-list").hidden = view !== "list";
}

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
    renderList(rows);
  } catch (error) {
    setStatus(error.message, true);
  }
}

// ---------- Загрузка CSV ----------

async function importFile(event) {
  const file = event.target.files[0];
  event.target.value = ""; // чтобы можно было выбрать тот же файл ещё раз
  if (!file) return;
  setStatus(`Загружаю ${file.name}…`);
  try {
    const text = await file.text();
    const result = await api("/api/import", { method: "POST", body: JSON.stringify({ csv: text }) });
    setStatus(`Загружено записей: ${result.imported}`);
    const month = result.months[result.months.length - 1];
    if (month && month !== state.month) setMonth(month);
    else await refresh();
  } catch (error) {
    setStatus(error.message, true);
  }
}

// ---------- Голосовой ввод (Chrome, Edge, Safari) ----------

function setupVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;
  const button = $("voice");
  button.hidden = false;
  const recognition = new Recognition();
  recognition.lang = "ru-RU";
  recognition.interimResults = false;
  let listening = false;

  recognition.onresult = (event) => {
    const said = Array.from(event.results).map((r) => r[0].transcript).join(" ");
    const current = $("text").value.trim();
    $("text").value = current ? `${current}, ${said}` : said;
  };
  recognition.onend = () => {
    listening = false;
    button.classList.remove("listening");
    button.textContent = "Голосом";
  };
  recognition.onerror = (event) => setStatus("Голосовой ввод не сработал: " + event.error, true);

  button.addEventListener("click", () => {
    if (listening) return recognition.stop();
    listening = true;
    button.classList.add("listening");
    button.textContent = "Остановить";
    recognition.start();
  });
}


// ---------- Вход и регистрация ----------

function showAuth() {
  state.user = null;
  $("app").hidden = true;
  document.querySelector(".month").hidden = true;
  $("account").hidden = true;
  $("auth").hidden = false;
  $("auth-email").focus();
}

function showApp(user) {
  state.user = user;
  $("auth").hidden = true;
  $("app").hidden = false;
  document.querySelector(".month").hidden = false;
  $("account").hidden = false;
  $("user-email").textContent = user.email;
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

// ---------- Запуск ----------

async function init() {
  $("date").value = todayISO();
  $("parse").addEventListener("click", parseText);
  $("save").addEventListener("click", savePreview);
  $("cancel").addEventListener("click", () => { state.preview = []; renderPreview(); setStatus(""); });
  $("prev-month").addEventListener("click", () => setMonth(shiftMonth(state.month, -1)));
  $("next-month").addEventListener("click", () => setMonth(shiftMonth(state.month, 1)));
  $("tab-table").addEventListener("click", () => setView("table"));
  $("tab-list").addEventListener("click", () => setView("list"));
  $("text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) parseText();
  });
  setupVoice();
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => state.summary && renderDailyChart(state.summary), 150);
  });
  setView(storage.get("view") === "list" ? "list" : "table");

  $("auth-form").addEventListener("submit", submitAuth);
  $("auth-switch").addEventListener("click", () => setAuthMode(state.authMode === "login" ? "register" : "login"));
  $("logout").addEventListener("click", logout);
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
  $("ai-note").textContent = health.ai_enabled
    ? "Текст разбирает ИИ: можно писать как угодно, например «вчера на такси ушло 300»."
    : "ИИ не подключён: работает простой разбор. Пишите «категория сумма» через запятую.";

  try {
    showApp(await api("/api/auth/me"));
  } catch (_) {
    showAuth();
  }
}

init().catch((error) => setStatus(error.message, true));
