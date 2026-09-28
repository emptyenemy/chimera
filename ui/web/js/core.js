"use strict";
/* Ядро фронта CHIMERA: мост к Python, стор, страницы, общие компоненты.

   Главное правило скорости: интерфейс никогда не ждёт бэкенд, чтобы что-то
   нарисовать. Состояние модулей пушит хаб (ui/hub.py) в Store, страницы рисуют
   из Store и подписаны на его ключи. Команды (api) уходят в фоне; тумблеры
   переключаются сразу (optimistic) и откатываются, если бэкенд ответил ошибкой.

   Перерисовка — morph(): новый HTML сравнивается с живым DOM и меняются только
   отличающиеся узлы. Фокус, выделение, скролл и hover не сбиваются, а одинаковый
   рендер вообще ничего не трогает. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Иконка lucide из спрайта (vendor/lucide/icons.js) — строкой, для шаблонов.
function ic(name, cls = "") {
  return `<svg class="icon${cls ? " " + cls : ""}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Не чаще раза в кадр: пачка результатов (пинги, стрим проверок) — одна перерисовка.
function rafThrottle(fn) {
  let queued = false;
  return () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; fn(); });
  };
}

// --- форматирование ----------------------------------------------------------

// Число по-русски: есть дробная часть — ровно 2 знака, нет — без запятой.
// Сначала toFixed(6) гасит мусор плавающей точки, потом копейку добираем по
// третьему знаку строки (прямой toFixed(2) врёт на числах вроде 1.005).
function fmtNum(n) {
  if (n == null || !isFinite(n)) return "—";
  const neg = n < 0;
  let [int, frac] = Math.abs(n).toFixed(6).split(".");
  let cents = parseInt(frac.slice(0, 2), 10);
  if (parseInt(frac[2], 10) >= 5) cents += 1;
  let i = BigInt(int);
  if (cents >= 100) { cents -= 100; i += 1n; }
  const intStr = i.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const out = cents ? `${intStr},${String(cents).padStart(2, "0")}` : intStr;
  return (neg ? "−" : "") + out;
}

function fmtBytes(b) {
  if (b == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0, v = Number(b);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${fmtNum(i ? Math.round(v * 100) / 100 : v)} ${u[i]}`;
}

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  if (d) return `${d} д ${h} ч`;
  if (h) return `${h} ч ${m} мин`;
  if (m) return `${m} мин ${s} с`;
  return `${s} с`;
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

// --- мост к Python (ui/api.py: Api.dispatch) ---------------------------------
// Движков три (config.json -> ui_backend) + мок для проверок без окна. Снаружи
// всё одно: Bridge.call(method, argsJson) -> Promise<resultJson>.

const Bridge = { call: null, push: null };

function initBridge() {
  if (window.__CHIMERA_MOCK__) {
    Bridge.call = (m, a) => window.__CHIMERA_MOCK__.call(m, a);
    return Promise.resolve();
  }
  if (window.qt && window.qt.webChannelTransport) return initQtBridge();
  // pywebview c 4.x тоже отдаёт страницу по http, поэтому браузерный режим
  // помечает себя сам маркером, который backend_browser.py пишет в <head>.
  if (window.__CHIMERA_HTTP__) return initHttpBridge();
  return initWebviewBridge();
}

// PySide6: слот bridge.call(callId, ...) отвечает сигналом resolved(callId, ...).
function initQtBridge() {
  return new Promise(resolve => {
    new QWebChannel(qt.webChannelTransport, channel => {
      const bridge = channel.objects.bridge;
      const pending = new Map();
      let seq = 0;
      bridge.resolved.connect((id, resultJson) => {
        const done = pending.get(id);
        if (done) { pending.delete(id); done(resultJson); }
      });
      bridge.pushed.connect((fn, payloadJson) => deliverPush(fn, JSON.parse(payloadJson)));
      Bridge.call = (method, argsJson) => new Promise(done => {
        const id = String(++seq);
        pending.set(id, done);
        bridge.call(id, method, argsJson);
      });
      resolve();
    });
  });
}

// pywebview: js_api отдаёт промис, пуши приходят вызовом window.<fn>() (evaluate_js).
function initWebviewBridge() {
  return new Promise(resolve => {
    const ready = () => {
      Bridge.call = (method, argsJson) => window.pywebview.api.call(method, argsJson);
      resolve();
    };
    if (window.pywebview && window.pywebview.api) ready();
    else window.addEventListener("pywebviewready", ready, { once: true });
  });
}

// Браузерный режим (ui/backend_browser.py): JSON-RPC по POST /api и long-poll /events.
// Токен выдан один раз в адресе, дальше ходит заголовком и из адреса убирается.
function initHttpBridge() {
  const token = window.__CHIMERA_TOKEN__ || new URLSearchParams(location.search).get("t") || "";
  if (location.search) history.replaceState(null, "", location.pathname + location.hash);
  Bridge.call = (method, args) =>
    fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Chimera-Token": token },
      body: JSON.stringify({ method, args }),
    }).then(r => {
      if (!r.ok) throw new Error(`мост вернул ${r.status}`);
      return r.text();
    });
  pumpEvents(token);
  return Promise.resolve();
}

// long-poll очереди пушей; он же heartbeat — пропала вкладка, сервер гасит программу
async function pumpEvents(token) {
  let cursor = 0;
  for (;;) {
    try {
      const r = await fetch(`/events?since=${cursor}`, { headers: { "X-Chimera-Token": token } });
      if (!r.ok) throw new Error(String(r.status));
      const data = await r.json();
      cursor = data.seq;
      for (const e of data.events) deliverPush(e.fn, e.payload);
    } catch {
      await sleep(1000);
    }
  }
}

// Вызов метода Api. Бросает Error с текстом ошибки бэкенда.
async function api(method, ...args) {
  const res = JSON.parse(await Bridge.call(method, JSON.stringify(args)));
  if (!res.ok) throw new Error(res.error || "Ошибка");
  return res.data;
}

// --- пуши из Python ------------------------------------------------------------
// Бэкенд зовёт window.<fn>(payload); здесь на каждое имя ставится трамплин,
// а страницы подписываются через onPush(fn, handler) — сколько угодно раз.

const _pushHandlers = new Map();
function deliverPush(fn, payload) {
  const list = _pushHandlers.get(fn);
  if (list) for (const h of list) { try { h(payload); } catch (e) { console.error(e); } }
}
function onPush(fn, handler) {
  if (!_pushHandlers.has(fn)) {
    _pushHandlers.set(fn, []);
    window[fn] = payload => deliverPush(fn, payload);  // pywebview зовёт window.<fn>
  }
  _pushHandlers.get(fn).push(handler);
}

// --- Store ---------------------------------------------------------------------
// Ключи хаба: winws, proxy, tg, hosts, filters, tgStats, dns (+ всё, что кладут
// страницы). set() оповещает подписчиков в следующем кадре и один раз на кадр —
// пачка пушей подряд даёт одну перерисовку.

const Store = (() => {
  const data = Object.create(null);
  const errors = Object.create(null);
  const subs = new Map();
  const dirty = new Set();
  let scheduled = false;

  function flush() {
    scheduled = false;
    const keys = Array.from(dirty);
    dirty.clear();
    const called = new Set();
    for (const k of keys) {
      for (const fn of subs.get(k) || []) {
        if (called.has(fn)) continue;   // подписчик на несколько ключей — один вызов
        called.add(fn);
        try { fn(); } catch (e) { console.error(e); }
      }
    }
  }
  function notify(key) {
    dirty.add(key);
    if (!scheduled) { scheduled = true; requestAnimationFrame(flush); }
  }
  return {
    get: key => data[key],
    error: key => errors[key],
    set(key, value) { data[key] = value; notify(key); },
    setError(key, err) { errors[key] = err; notify(key); },
    // слияние с текущим (для оптимистичных правок)
    patch(key, part) { data[key] = { ...(data[key] || {}), ...part }; notify(key); },
    // подписка на один или несколько ключей; возвращает отписку
    on(keys, fn) {
      for (const k of [].concat(keys)) {
        if (!subs.has(k)) subs.set(k, new Set());
        subs.get(k).add(fn);
      }
      return () => { for (const k of [].concat(keys)) subs.get(k)?.delete(fn); };
    },
  };
})();

// Пуш хаба: { key, data, error, ts }. Пока идёт оптимистичная правка ключа —
// снимок в полёте мог уйти до команды, он бы откатил тумблер назад. Такие
// пропускаем: после команды хаб всё равно пришлёт свежий (poke).
const _pendingKeys = new Map();   // key -> счётчик незавершённых оптимистичных действий
onPush("hub", p => {
  if (!p || !p.key) return;
  if (_pendingKeys.get(p.key)) return;
  if (p.data != null) Store.set(p.key, p.data);
  Store.setError(p.key, p.error || null);
});

// Оптимистичное действие: сразу патчит стор, шлёт команду, результат (если это
// объект состояния) кладёт в стор, при ошибке откатывает и показывает тост.
async function optimistic(key, patch, call, { applyResult = true, errorTitle } = {}) {
  const before = Store.get(key);
  _pendingKeys.set(key, (_pendingKeys.get(key) || 0) + 1);
  if (patch) Store.patch(key, patch);
  try {
    const res = await call();
    if (applyResult && res && typeof res === "object" && !Array.isArray(res)) Store.patch(key, res);
    return res;
  } catch (e) {
    Store.set(key, before);
    toast.error(errorTitle || "Не получилось", e.message);
    throw e;
  } finally {
    const n = (_pendingKeys.get(key) || 1) - 1;
    if (n) _pendingKeys.set(key, n); else _pendingKeys.delete(key);
    api("hub_refresh", [key]).catch(() => {});
  }
}

// --- morph: точечное обновление DOM ---------------------------------------------
// Ключ узла — data-key или id: по ним переставляем, а не пересоздаём. Узел с
// data-morph="skip" не трогаем внутри (им управляет код — лог, редактор).

function _key(n) {
  return n.nodeType === 1 ? (n.getAttribute("data-key") || n.id || null) : null;
}

function _syncAttrs(a, b) {
  for (const { name } of Array.from(a.attributes)) if (!b.hasAttribute(name)) a.removeAttribute(name);
  for (const { name, value } of Array.from(b.attributes)) if (a.getAttribute(name) !== value) a.setAttribute(name, value);
}

function _morphNode(a, b) {
  if (a.nodeType !== 1) {
    if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue;
    return;
  }
  _syncAttrs(a, b);
  const tag = a.nodeName;
  if (tag === "INPUT") {
    // поле, в котором сейчас печатают, не перетираем
    if (document.activeElement !== a) {
      const v = b.getAttribute("value") ?? "";
      if (a.value !== v && a.type !== "checkbox" && a.type !== "radio") a.value = v;
    }
    a.checked = b.hasAttribute("checked");
    return;
  }
  if (tag === "TEXTAREA") {
    if (document.activeElement !== a && a.value !== b.textContent) a.value = b.textContent;
    return;
  }
  if (a.getAttribute("data-morph") === "skip") return;
  _morphChildren(a, b);
  if (tag === "SELECT") {
    const sel = b.querySelector("option[selected]");
    if (sel && a.value !== sel.value && document.activeElement !== a) a.value = sel.value;
  }
}

function _morphChildren(from, to) {
  const keyed = new Map();
  for (const c of from.childNodes) { const k = _key(c); if (k) keyed.set(k, c); }
  let cur = from.firstChild;
  for (const n of Array.from(to.childNodes)) {
    const k = _key(n);
    let match = null;
    if (k) {
      match = keyed.get(k) || null;
      if (match) keyed.delete(k);
    } else if (cur && !_key(cur) && cur.nodeType === n.nodeType && cur.nodeName === n.nodeName) {
      match = cur;
    }
    if (match) {
      if (match === cur) cur = cur.nextSibling;
      else from.insertBefore(match, cur);
      _morphNode(match, n);
    } else {
      from.insertBefore(n, cur);
    }
  }
  while (cur) { const next = cur.nextSibling; from.removeChild(cur); cur = next; }
}

// Главная функция рендера: morph(el, html). Одинаковый HTML — ноль работы.
function morph(el, html) {
  if (!el || el.__html === html) return;
  el.__html = html;
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  if (window.icons) window.icons(tpl.content);  // <i data-icon> -> <svg> до сравнения
  _morphChildren(el, tpl.content);
}

// --- страницы и навигация --------------------------------------------------------
// Страница — объект { id, title, icon, group, mount(root, ctx), show(ctx), hide(ctx) }.
// mount зовётся один раз при первом показе (старт окна не платит за все вкладки),
// show/hide — на каждый вход/выход. ctx.every() — опрос, живущий только пока
// страница видна; ctx.watch() — подписка на ленивые источники хаба.

const Pages = (() => {
  const list = [];
  const byId = new Map();
  let current = null;

  function define(page) {
    list.push(page);
    byId.set(page.id, page);
  }

  function makeCtx(page) {
    const ctx = {
      page,
      timers: [],
      watched: [],
      unsubs: [],
      // периодическая задача: следующий запуск — только после завершения прошлого
      every(ms, fn, { immediate = true } = {}) {
        const t = { stopped: false, id: 0 };
        const tick = async () => {
          if (t.stopped) return;
          if (!document.hidden) { try { await fn(); } catch (e) { console.error(e); } }
          if (!t.stopped) t.id = setTimeout(tick, ms);
        };
        if (immediate) tick(); else t.id = setTimeout(tick, ms);
        ctx.timers.push(t);
        return t;
      },
      watch(keys) {
        keys = [].concat(keys);
        ctx.watched.push(...keys);
        api("hub_watch", keys, true).catch(() => {});
      },
      // подписка на стор, снимается при уходе со страницы
      on(keys, fn) { ctx.unsubs.push(Store.on(keys, fn)); },
      stopAll() {
        for (const t of ctx.timers) { t.stopped = true; clearTimeout(t.id); }
        ctx.timers = [];
        if (ctx.watched.length) api("hub_watch", ctx.watched, false).catch(() => {});
        ctx.watched = [];
        for (const u of ctx.unsubs) u();
        ctx.unsubs = [];
      },
    };
    return ctx;
  }

  function go(id, { push = true } = {}) {
    const page = byId.get(id) || list[0];
    if (!page) return;
    if (current === page) return;
    if (current) {
      try { current.hide?.(current.__ctx); } catch (e) { console.error(e); }
      current.__ctx.stopAll();
      current.__root.hidden = true;
    }
    current = page;
    if (!page.__root) {
      page.__root = document.createElement("section");
      page.__root.className = "page";
      page.__root.dataset.page = page.id;
      $("#main").appendChild(page.__root);
      page.__ctx = makeCtx(page);
      try { page.mount?.(page.__root, page.__ctx); } catch (e) { console.error(e); }
      if (window.icons) window.icons(page.__root);
    }
    page.__root.hidden = false;
    $("#main").scrollTop = 0;
    try { page.show?.(page.__ctx); } catch (e) { console.error(e); }
    for (const b of $$(".sb-item[data-page]")) {
      if (b.dataset.page === page.id) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    }
    document.title = `${page.title} — CHIMERA`;
    if (push && location.hash !== "#" + page.id) history.replaceState(null, "", "#" + page.id);
    try { localStorage.setItem("chimera.page", page.id); } catch {}
  }

  function renderNav() {
    const groups = [];
    for (const p of list) {
      let g = groups.find(x => x.name === (p.group || ""));
      if (!g) groups.push(g = { name: p.group || "", pages: [] });
      g.pages.push(p);
    }
    $("#sb-nav").innerHTML = groups.map(g => `
      <div class="sb-group">
        ${g.name ? `<div class="sb-label">${esc(g.name)}</div>` : ""}
        ${g.pages.map(p => `
          <button class="sb-item" data-page="${p.id}">
            ${ic(p.icon)}<span>${esc(p.title)}</span>
            <span class="sb-dot" data-nav-dot="${p.id}"></span>
          </button>`).join("")}
      </div>`).join("");
    $("#sb-nav").addEventListener("click", e => {
      const b = e.target.closest(".sb-item[data-page]");
      if (b) go(b.dataset.page);
    });
  }

  return {
    define, go, renderNav,
    get current() { return current; },
    get list() { return list; },
    initial() {
      const fromHash = location.hash.slice(1);
      let saved = null;
      try { saved = localStorage.getItem("chimera.page"); } catch {}
      return byId.has(fromHash) ? fromHash : (byId.has(saved) ? saved : list[0]?.id);
    },
  };
})();

// --- Toast (sonner) ---------------------------------------------------------------

function toast(title, desc, type = "info", ms = 4000) {
  const box = $("#toaster");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const iconName = { success: "circle-check", error: "circle-x", info: "info", warning: "triangle-alert" }[type] || "info";
  el.innerHTML = `${ic(iconName)}<div class="toast-body"><div class="toast-title">${esc(title)}</div>${
    desc ? `<div class="toast-desc">${esc(desc)}</div>` : ""}</div>`;
  box.appendChild(el);
  while (box.children.length > 4) box.firstChild.remove();
  const close = () => { el.classList.add("out"); setTimeout(() => el.remove(), 160); };
  el.addEventListener("click", close);
  setTimeout(close, type === "error" ? Math.max(ms, 6000) : ms);
}
toast.success = (t, d) => toast(t, d, "success");
toast.error = (t, d) => toast(t, d, "error");
toast.info = (t, d) => toast(t, d, "info");
toast.warning = (t, d) => toast(t, d, "warning");

// --- Dialog -------------------------------------------------------------------------
// openDialog({ title, description, body, footer, wide, onMount }) -> { el, close }
// body/footer — HTML-строки. Закрытие: Escape, клик по фону, [data-close].

function openDialog({ title, description, body = "", footer = "", wide = false, onMount, onClose } = {}) {
  const overlay = document.createElement("div");
  overlay.className = "dialog-overlay";
  overlay.innerHTML = `
    <div class="dialog-content${wide ? " wide" : ""}" role="dialog" aria-modal="true">
      <button class="btn ghost sm icon-btn dialog-close" data-close aria-label="Закрыть">${ic("x")}</button>
      ${title || description ? `<div class="dialog-header">
        ${title ? `<h2 class="dialog-title">${esc(title)}</h2>` : ""}
        ${description ? `<p class="dialog-description">${esc(description)}</p>` : ""}
      </div>` : ""}
      ${body}
      ${footer ? `<div class="dialog-footer">${footer}</div>` : ""}
    </div>`;
  if (window.icons) window.icons(overlay);
  document.body.appendChild(overlay);
  const prevFocus = document.activeElement;
  let closed = false;
  const close = result => {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    prevFocus?.focus?.();
    onClose?.(result);
  };
  const onKey = e => { if (e.key === "Escape") { e.stopPropagation(); close(undefined); } };
  document.addEventListener("keydown", onKey, true);
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) close(undefined); });
  overlay.addEventListener("click", e => { if (e.target.closest("[data-close]")) close(undefined); });
  const handle = { el: overlay.firstElementChild, close };
  onMount?.(handle);
  const first = overlay.querySelector("input, textarea, select, .btn:not(.dialog-close)");
  first?.focus();
  return handle;
}

// Подтверждение — вместо window.confirm(). destructive — красная кнопка.
function confirmDialog({ title, description, confirmText = "Подтвердить", cancelText = "Отмена", destructive = false }) {
  return new Promise(resolve => {
    openDialog({
      title, description,
      footer: `<button class="btn outline" data-close>${esc(cancelText)}</button>
               <button class="btn${destructive ? " destructive" : ""}" data-ok>${esc(confirmText)}</button>`,
      onMount: h => h.el.querySelector("[data-ok]").addEventListener("click", () => h.close(true)),
      onClose: r => resolve(r === true),
    });
  });
}

// Ввод строки — вместо window.prompt(). null — отмена.
function promptDialog({ title, description, label = "", value = "", placeholder = "", confirmText = "Сохранить", mono = false }) {
  return new Promise(resolve => {
    openDialog({
      title, description,
      body: `<div class="field">${label ? `<label class="label">${esc(label)}</label>` : ""}
        <input class="input${mono ? " mono" : ""}" data-input value="${esc(value)}" placeholder="${esc(placeholder)}"></div>`,
      footer: `<button class="btn outline" data-close>Отмена</button><button class="btn" data-ok>${esc(confirmText)}</button>`,
      onMount: h => {
        const inp = h.el.querySelector("[data-input]");
        const ok = () => h.close(inp.value);
        h.el.querySelector("[data-ok]").addEventListener("click", ok);
        inp.addEventListener("keydown", e => { if (e.key === "Enter") ok(); });
        setTimeout(() => { inp.focus(); inp.select(); });
      },
      onClose: r => resolve(typeof r === "string" ? r : null),
    });
  });
}

// --- Меню (DropdownMenu / контекстное) ------------------------------------------------
// items: [{ label, icon, onSelect, destructive, disabled } | "sep" | { label, heading: true }]

function openMenu(x, y, items) {
  closeMenu();
  const el = document.createElement("div");
  el.className = "menu";
  el.id = "ctx-menu";
  el.innerHTML = items.map((it, i) => {
    if (it === "sep") return `<div class="menu-sep"></div>`;
    if (it.heading) return `<div class="menu-label">${esc(it.label)}</div>`;
    return `<button class="menu-item${it.destructive ? " destructive" : ""}" data-i="${i}" ${it.disabled ? "disabled" : ""}>
      ${it.icon ? ic(it.icon) : ""}<span>${esc(it.label)}</span></button>`;
  }).join("");
  document.body.appendChild(el);
  const r = el.getBoundingClientRect();
  el.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  el.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
  el.addEventListener("click", e => {
    const b = e.target.closest("[data-i]");
    if (!b) return;
    closeMenu();
    items[+b.dataset.i].onSelect?.();
  });
  setTimeout(() => document.addEventListener("mousedown", _menuOutside, true));
  return el;
}
function _menuOutside(e) { if (!e.target.closest("#ctx-menu")) closeMenu(); }
function closeMenu() {
  $("#ctx-menu")?.remove();
  document.removeEventListener("mousedown", _menuOutside, true);
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });

// --- Tooltip: data-tip="текст" на любом элементе ------------------------------------

(() => {
  let tip = null, timer = 0, owner = null;
  const hide = () => { clearTimeout(timer); tip?.remove(); tip = null; owner = null; };
  document.addEventListener("mouseover", e => {
    const t = e.target.closest("[data-tip]");
    if (t === owner) return;
    hide();
    if (!t) return;
    owner = t;
    timer = setTimeout(() => {
      if (!owner?.isConnected) return;
      tip = document.createElement("div");
      tip.className = "tooltip";
      tip.textContent = owner.dataset.tip;
      document.body.appendChild(tip);
      const r = owner.getBoundingClientRect(), tr = tip.getBoundingClientRect();
      let top = r.top - tr.height - 6;
      if (top < 4) top = r.bottom + 6;
      tip.style.top = top + "px";
      tip.style.left = Math.max(4, Math.min(r.left + r.width / 2 - tr.width / 2, innerWidth - tr.width - 4)) + "px";
    }, 350);
  });
  document.addEventListener("mousedown", hide, true);
  document.addEventListener("scroll", hide, true);
})();

// --- мелкие компоненты-строки ------------------------------------------------------

// Switch shadcn: <button role="switch">. attrs — строка доп. атрибутов (data-*).
function switchHtml(checked, attrs = "", { disabled = false, pending = false } = {}) {
  return `<button type="button" role="switch" class="switch${pending ? " pending" : ""}" aria-checked="${checked ? "true" : "false"}" ${disabled ? "disabled" : ""} ${attrs}><span class="thumb"></span></button>`;
}

function badgeHtml(text, variant = "secondary", icon = "") {
  return `<span class="badge ${variant}">${icon ? ic(icon) : ""}${esc(text)}</span>`;
}

function emptyHtml({ icon = "info", title = "", desc = "", action = "" } = {}) {
  return `<div class="empty">${icon ? `<div class="empty-media">${ic(icon)}</div>` : ""}
    ${title ? `<div class="empty-title">${esc(title)}</div>` : ""}
    ${desc ? `<div class="empty-desc">${esc(desc)}</div>` : ""}${action}</div>`;
}

function skeletonHtml(lines = 3, h = 36) {
  return `<div class="stack-sm">${Array.from({ length: lines }, () => `<div class="skeleton" style="height:${h}px"></div>`).join("")}</div>`;
}

// Кнопка в состоянии «работаю»: блокируется, первая иконка крутится (или появляется
// спиннер). Возвращает результат промиса. Повторный клик по занятой — игнор.
async function withBusy(btn, fn) {
  if (!btn || btn.classList.contains("busy")) return;
  btn.classList.add("busy");
  btn.setAttribute("aria-disabled", "true");
  let added = null;
  if (!btn.querySelector(".icon")) {
    btn.insertAdjacentHTML("afterbegin", ic("loader-circle"));
    added = btn.firstElementChild;
  }
  try { return await fn(); }
  finally {
    btn.classList.remove("busy");
    btn.removeAttribute("aria-disabled");
    added?.remove();
  }
}

// Скопировать в буфер (в WebView2/QtWebEngine clipboard API есть не всегда)
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast.success("Скопировано");
}

// --- LogView: живой лог с инкрементальной догрузкой ---------------------------------
// method — метод Api вида *_log(offset) -> {offset, data, reset}. Строки дописываются
// в конец (без перерисовки старых), хвост ограничен maxLines. Автопрокрутка — только
// если пользователь и так внизу: читать середину лога поток не мешает.

class LogView {
  constructor(el, method, { maxLines = 1500, interval = 700 } = {}) {
    this.el = el;
    this.method = method;
    this.maxLines = maxLines;
    this.interval = interval;
    this.offset = 0;
    this.lines = 0;
    el.classList.add("log");
    el.setAttribute("data-morph", "skip");
  }
  static cls(line) {
    if (/\b(error|fatal|panic|fail(ed)?|ошибк)/i.test(line)) return "l-err";
    if (/\b(warn(ing)?|предупр)/i.test(line)) return "l-warn";
    if (/\b(started|listening|ready|запущен|ok)\b/i.test(line)) return "l-ok";
    return "";
  }
  async poll() {
    const r = await api(this.method, this.offset);
    if (r.reset) { this.el.textContent = ""; this.lines = 0; }
    this.offset = r.offset;
    if (!r.data) return;
    const atBottom = this.el.scrollHeight - this.el.scrollTop - this.el.clientHeight < 24;
    let text = r.data;
    // первый запрос отдаёт весь файл — берём только хвост
    const all = text.split("\n");
    if (all.length > this.maxLines) text = all.slice(-this.maxLines).join("\n");
    const frag = document.createDocumentFragment();
    for (const line of text.split("\n")) {
      if (!line) continue;
      const div = document.createElement("div");
      const c = LogView.cls(line);
      if (c) div.className = c;
      div.textContent = line;
      frag.appendChild(div);
      this.lines++;
    }
    this.el.appendChild(frag);
    while (this.lines > this.maxLines && this.el.firstChild) { this.el.firstChild.remove(); this.lines--; }
    if (atBottom) this.el.scrollTop = this.el.scrollHeight;
  }
  // запустить в контексте страницы (живёт, пока страница видна)
  attach(ctx) { return ctx.every(this.interval, () => this.poll()); }
  clear() { this.el.textContent = ""; this.lines = 0; }
}

// --- старт ---------------------------------------------------------------------------

const App = { info: { admin: true, version: "" } };

async function boot() {
  Pages.renderNav();
  await initBridge();
  // снимок хаба — мгновенно (всё, что уже опрошено), дальше живут пуши
  try {
    const snap = await api("hub_snapshot");
    for (const [k, v] of Object.entries(snap || {})) Store.set(k, v);
  } catch (e) { console.error(e); }
  try { App.info = await api("app_info"); } catch {}
  Store.set("app", App.info);
  Pages.go(Pages.initial(), { push: false });
  window.addEventListener("hashchange", () => Pages.go(location.hash.slice(1), { push: false }));
  document.body.classList.add("ready");
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch(e => { console.error(e); toast.error("Не удалось запустить интерфейс", e.message); });
});
