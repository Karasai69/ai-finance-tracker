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
};

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
        categorySelect(item.category, (value) => (item.category = value)),
        el("input", { type: "number", min: "0", step: "any", value: item.amount, "aria-label": "Сумма",
          onchange: (e) => (item.amount = Number(e.target.value)) }),
        el("input", { class: "desc", type: "text", value: item.description, "aria-label": "Описание",
          onchange: (e) => (item.description = e.target.value) }),
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
    $("source").textContent = result.source === "ai" ? "(разобрал ИИ)" : "(простой разбор)";
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
    setStatus(`Сохранено записей: ${items.length}`);
    const savedMonth = items[0].date.slice(0, 7);
    if (savedMonth !== state.month) setMonth(savedMonth);
    else await refresh();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    $("save").disabled = false;
  }
}

// ---------- Итоги ----------

function renderSummary(summary) {
  $("sum-income").textContent = money(summary.income);
  $("sum-expense").textContent = money(summary.expense);
  $("sum-lent").textContent = money(summary.lent);
  $("sum-balance").textContent = money(summary.balance);
  $("sum-balance").classList.toggle("negative", summary.balance < 0);

  const expenses = summary.by_category.filter((c) => c.kind === "expense");
  const max = Math.max(...expenses.map((c) => c.total), 1);
  const box = $("categories");
  box.replaceChildren();
  if (!expenses.length) {
    box.append(el("p", { class: "empty" }, "В этом месяце расходов нет."));
    return;
  }
  for (const cat of expenses) {
    const pct = summary.expense ? (cat.total / summary.expense) * 100 : 0;
    const share = pct > 0 && pct < 1 ? "<1" : Math.round(pct);
    const fill = el("div", { class: "bar-fill" });
    fill.style.width = `${(cat.total / max) * 100}%`;
    box.append(el("div", { class: "bar" },
      el("span", {}, cat.name),
      el("div", { class: "bar-track" }, fill),
      el("b", {}, money(cat.total), el("small", {}, `${share}%`)),
    ));
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

  // Суммы по дням
  const cells = new Map(); // "2026-11-04|transport" -> { total, notes[], rows[] }
  const add = (key, row) => {
    const cell = cells.get(key) || { total: 0, notes: [], rows: [] };
    cell.total += row.amount;
    cell.notes.push(`${row.description || state.names[row.category]}: ${fmt(row.amount)}`);
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
      const sign = row.kind === "income" ? "+" : "−";
      group.append(el("div", { class: "tx" },
        el("div", {},
          el("div", {}, row.description || state.names[row.category]),
          el("div", { class: "tx-cat" }, state.names[row.category] || row.category),
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
    const draft = { date: row.date, category: row.category, amount: row.amount, description: row.description };
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
        await api(`/api/transactions/${row.id}`, { method: "PATCH", body: JSON.stringify(draft) });
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
        el("label", {}, "Категория", categorySelect(row.category, (v) => (draft.category = v))),
        el("label", {}, "Сумма, ₸", el("input", { type: "number", min: "0", step: "any", value: row.amount,
          onchange: (e) => (draft.amount = Number(e.target.value)) })),
        el("label", { class: "wide" }, "Описание", el("input", { type: "text", value: row.description, maxlength: "300",
          onchange: (e) => (draft.description = e.target.value) })),
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
    const [summary, rows] = await Promise.all([
      api(`/api/summary?month=${month}`),
      api(`/api/transactions?month=${month}`),
    ]);
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
  setView(storage.get("view") === "list" ? "list" : "table");

  $("auth-form").addEventListener("submit", submitAuth);
  $("auth-switch").addEventListener("click", () => setAuthMode(state.authMode === "login" ? "register" : "login"));
  $("logout").addEventListener("click", logout);
  $("import").addEventListener("click", () => $("import-file").click());
  $("editor-close").addEventListener("click", () => $("editor").close());
  $("editor").addEventListener("click", (e) => { if (e.target === $("editor")) $("editor").close(); });
  $("import-file").addEventListener("change", importFile);
  state.month = todayISO().slice(0, 7);

  const [data, health] = await Promise.all([api("/api/categories"), api("/api/health")]);
  state.categories = data.categories;
  state.names = Object.fromEntries(data.categories.map((c) => [c.key, c.name]));
  state.order = Object.fromEntries(data.categories.map((c, i) => [c.key, i]));
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
