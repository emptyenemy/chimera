"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), 3500);
}

// --- мост к Python (см. ui/api.py: Api.dispatch) -----------------------------
// Движков окна два (config.json -> ui_backend), мост у каждого свой, поэтому тут
// один общий вид: _call(method, argsJson) -> Promise<resultJson>. Какой именно —
// определяем по тому, что подсунуто в страницу, флаг с бэкенда не нужен.

let _call = null;

function initBridge() {
  if (window.qt && window.qt.webChannelTransport) return initQtBridge();
  // По протоколу страницы движок не опознать: pywebview c 4.x тоже отдаёт файлы
  // своим http-сервером, а не с file://. Поэтому браузерный режим помечает себя
  // сам — маркером, который backend_browser.py дописывает в <head> страницы.
  if (window.__CHIMERA_HTTP__) return initHttpBridge();
  return initWebviewBridge();
}

// PySide6: слот bridge.call(callId, ...) отвечает не возвратом, а сигналом
// resolved(callId, ...) — по нему и резолвим промис (см. ui/backend_qt.py).
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
      // сигнал pushed(fn, jsonPayload) — стриминг результатов (чебур/блокчек)
      bridge.pushed.connect((fn, payloadJson) => {
        const handler = window[fn];
        if (handler) handler(JSON.parse(payloadJson));
      });
      _call = (method, argsJson) => new Promise(done => {
        const id = String(++seq);
        pending.set(id, done);
        bridge.call(id, method, argsJson);
      });
      resolve();
    });
  });
}

// pywebview: js_api уже отдаёт промис, а стриминг прилетает вызовом window.<fn>()
// через evaluate_js — подключать тут нечего.
function initWebviewBridge() {
  return new Promise(resolve => {
    const ready = () => {
      _call = (method, argsJson) => window.pywebview.api.call(method, argsJson);
      resolve();
    };
    if (window.pywebview && window.pywebview.api) ready();
    else window.addEventListener("pywebviewready", ready, { once: true });
  });
}

// Браузерный режим (ui/backend_browser.py): страница пришла по http, значит моста
// в странице нет — говорим с Python обычными запросами. Токен выдан один раз в
// адресе, дальше ходит заголовком, чтобы не светиться в истории и Referer.
function initHttpBridge() {
  const token = window.__CHIMERA_TOKEN__ || new URLSearchParams(location.search).get("t") || "";
  // токен уже у нас (и в cookie) — убираем его из адресной строки, чтобы не уехал
  // в историю браузера и в Referer
  if (location.search) history.replaceState(null, "", location.pathname);
  _call = (method, argsJson) =>
    fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Chimera-Token": token },
      body: JSON.stringify({ method, args: argsJson }),
    }).then(r => {
      if (!r.ok) throw new Error(`мост вернул ${r.status}`);
      return r.text();
    });
  pumpEvents(token);
  return Promise.resolve();
}

// long-poll очереди push'ей: то же, что evaluate_js у pywebview — зовём window.<fn>().
// Запрос висит до события или до таймаута сервера, поэтому это же и heartbeat:
// пропала вкладка — сервер через полторы минуты гасит программу.
async function pumpEvents(token) {
  let cursor = 0;
  for (;;) {
    try {
      const r = await fetch(`/events?since=${cursor}`, { headers: { "X-Chimera-Token": token } });
      if (!r.ok) throw new Error(String(r.status));
      const data = await r.json();
      cursor = data.seq;
      for (const e of data.events) {
        const handler = window[e.fn];
        if (handler) handler(e.payload);
      }
    } catch {
      await new Promise(r => setTimeout(r, 1000));  // сервер лёг/перезапуск — пробуем снова
    }
  }
}

async function api(method, ...args) {
  const res = JSON.parse(await _call(method, JSON.stringify(args)));
  if (!res.ok) throw new Error(res.error);
  return res.data;
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// Иконка из встроенного Lucide-спрайта (см. index.html). Цвет/размер — через CSS.
function icon(name, cls = "") {
  return `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

// --- модалки (замена нативным confirm()/prompt() — блюр фона + карточка) ---

function confirmModal({ title, description, confirmLabel = "Удалить", cancelLabel = "Отмена", danger = true }) {
  return new Promise(resolve => {
    const backdrop = $("#confirm-modal");
    $("#confirm-title").textContent = title;
    $("#confirm-desc").textContent = description;
    const okBtn = $("#confirm-ok-btn");
    const cancelBtn = $("#confirm-cancel-btn");
    okBtn.textContent = confirmLabel;
    okBtn.className = "btn" + (danger ? " danger" : " primary");
    cancelBtn.textContent = cancelLabel;

    const done = result => {
      backdrop.classList.remove("show");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      backdrop.removeEventListener("mousedown", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => done(true);
    const onCancel = () => done(false);
    const onBackdrop = e => { if (e.target === backdrop) done(false); };
    const onKey = e => {
      if (e.key === "Escape") done(false);
      if (e.key === "Enter") done(true);
    };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    backdrop.addEventListener("mousedown", onBackdrop);
    document.addEventListener("keydown", onKey);
    backdrop.classList.add("show");
    okBtn.focus();
  });
}

function promptModal({ title, description, value = "", confirmLabel = "Сохранить", validate }) {
  return new Promise(resolve => {
    const backdrop = $("#prompt-modal");
    const input = $("#prompt-input");
    const errEl = $("#prompt-error");
    $("#prompt-title").textContent = title;
    $("#prompt-desc").textContent = description || "";
    $("#prompt-desc").style.display = description ? "" : "none";
    $("#prompt-ok-btn").textContent = confirmLabel;
    input.value = value;
    errEl.textContent = "";

    const done = result => {
      backdrop.classList.remove("show");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      backdrop.removeEventListener("mousedown", onBackdrop);
      input.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => {
      const v = input.value.trim();
      if (validate) {
        const err = validate(v);
        if (err) { errEl.textContent = err; return; }
      }
      done(v);
    };
    const onCancel = () => done(null);
    const onBackdrop = e => { if (e.target === backdrop) done(null); };
    const onKey = e => {
      if (e.key === "Escape") done(null);
      if (e.key === "Enter") onOk();
    };

    const okBtn = $("#prompt-ok-btn");
    const cancelBtn = $("#prompt-cancel-btn");
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    backdrop.addEventListener("mousedown", onBackdrop);
    input.addEventListener("keydown", onKey);
    backdrop.classList.add("show");
    input.focus();
    input.select();
  });
}

// --- hosts tab --------------------------------------------------------------

let hostsState = { applied: false, assignments: {}, count: 0 };
let hostsProviders = [];
let hostsLists = [];
let assignments = {};          // {provider_id: [list_name, ...]} — мирорим на фронте
let selectedProvider = null;

async function loadHosts() {
  let data;
  try {
    data = await api("hosts_overview");
  } catch (e) {
    $("#hosts-error").textContent = e.message;
    return;
  }
  hostsState = data.state;
  hostsProviders = data.providers;
  hostsLists = data.lists;
  assignments = { ...data.state.assignments };
  selectedProvider = selectedProvider || hostsProviders[0]?.id || null;

  // провайдеры слева (строятся один раз; пинг и счётчики обновляются точечно)
  $("#hosts-providers").innerHTML = hostsProviders.map(p => `
    <div class="prov-row ${p.id === selectedProvider ? "selected" : ""}" data-id="${p.id}">
      <input type="radio" name="hprov" ${p.id === selectedProvider ? "checked" : ""}>
      <span class="prov-name">${esc(p.name)} <span class="badge on" data-count hidden></span></span>
      <span class="prov-ping" data-ping></span>
      ${p.builtin ? "" : `<span class="prov-x" data-act="del" title="Удалить">×</span>`}
    </div>
  `).join("");

  renderLists();
  updateProviderCounts();
  renderHostsStatus();
  if (hostsPingOn) { stopHostsPing(); startHostsPing(); }  // перецепить пинг на новый набор строк
}

// какому провайдеру назначен список (или null)
function listOwner(name) {
  for (const pid in assignments) if (assignments[pid].includes(name)) return pid;
  return null;
}

function providerName(id) {
  return hostsProviders.find(p => p.id === id)?.name || id;
}

// правая панель: списки для ВЫБРАННОГО провайдера
function renderLists() {
  const box = $("#hosts-lists");
  if (!hostsLists.length) {
    box.innerHTML = `<div class="empty">Списков нет — добавь во вкладке «Списки».</div>`;
    return;
  }
  box.innerHTML = hostsLists.map(l => {
    const owner = listOwner(l.name);
    const mine = owner === selectedProvider;
    const elsewhere = owner && !mine;
    return `
    <label class="list-check ${elsewhere ? "taken" : ""}">
      <input type="checkbox" value="${esc(l.name)}" ${mine ? "checked" : ""}>
      <span class="lc-name">${esc(l.name)}</span>
      ${elsewhere ? `<span class="lc-owner">→ ${esc(providerName(owner))}</span>` : `<span class="lc-count">${l.count}</span>`}
    </label>`;
  }).join("");
}

function updateProviderCounts() {
  document.querySelectorAll("#hosts-providers .prov-row").forEach(row => {
    const n = (assignments[row.dataset.id] || []).length;
    const badge = row.querySelector("[data-count]");
    badge.hidden = n === 0;
    badge.textContent = n;
  });
}

// клик по списку: назначить выбранному провайдеру (эксклюзивно) или снять —
// и сразу применить (галочка = работает, снял = выключилось)
function onListToggle(e) {
  const cb = e.target.closest("input[type=checkbox]");
  if (!cb || !selectedProvider) return;
  const name = cb.value;
  for (const pid in assignments) assignments[pid] = assignments[pid].filter(x => x !== name);
  if (cb.checked) (assignments[selectedProvider] ||= []).push(name);
  for (const pid in assignments) if (!assignments[pid].length) delete assignments[pid];

  renderLists();
  updateProviderCounts();
  syncHosts();
}

// синхронизация hosts с привязками; быстрые клики коалесируются (последний побеждает)
let hostsSyncing = false;
let hostsSyncPending = false;

async function syncHosts() {
  if (hostsSyncing) { hostsSyncPending = true; renderHostsStatus(true); return; }
  hostsSyncing = true;
  $("#hosts-error").textContent = "";
  renderHostsStatus(true);
  do {
    hostsSyncPending = false;
    try {
      hostsState = await api("hosts_set_assignments", assignments);
    } catch (err) {
      $("#hosts-error").textContent = err.message;
    }
  } while (hostsSyncPending);
  hostsSyncing = false;
  renderHostsStatus();
}

function renderHostsStatus(busy = false) {
  const box = $("#hosts-status");
  box.hidden = false;
  // тумблер отражает РЕАЛЬНОЕ состояние (записан ли блок в hosts), а не намерение —
  // так он совпадает с карточкой на дашборде
  $("#hosts-enabled").checked = !!hostsState.applied;
  const pairs = Object.entries(assignments).filter(([, l]) => l.length);
  const summary = pairs.map(([pid, l]) => `${providerName(pid)}: ${l.join(", ")}`).join("  ·  ");
  if (busy) {
    box.className = "hosts-status off";
    box.textContent = `Применяю…  ${summary}`;
  } else if (hostsState.enabled === false) {
    box.className = "hosts-status off";
    box.textContent = pairs.length ? `Выключено. Привязки сохранены: ${summary}` : "Выключено.";
  } else if (pairs.length && hostsState.applied) {
    box.className = "hosts-status on";
    box.textContent = `✓ Работает (${hostsState.count} записей в hosts)  ·  ${summary}`;
  } else {
    box.className = "hosts-status off";
    box.textContent = "Ничего не включено. Выбери провайдера слева и отметь сервисы справа.";
  }
}

async function onHostsToggle(e) {
  const on = e.target.checked;
  try {
    hostsState = await api("hosts_set_enabled", on);
    renderHostsStatus();  // перерисует тумблер от факта (applied) — снимется сам, если включать нечего
    toast(hostsState.applied ? "Разблокировка hosts включена."
          : on ? "Нечего включать — сначала отметь сервисы."
               : "Разблокировка hosts выключена — привязки сохранены.");
  } catch (err) {
    e.target.checked = !on;  // откат тумблера при ошибке
    toast(err.message, true);
  }
}

// автопинг провайдеров, только пока открыта вкладка Hosts.
// Каждый провайдер пингуется СВОИМ циклом — медленный не тормозит остальных.
let hostsPingOn = false;
const hostsPingTimers = {};

function renderPing(r) {
  const row = document.querySelector(`#hosts-providers .prov-row[data-id="${r.id}"]`);
  const el = row?.querySelector("[data-ping]");
  if (!el) return;
  el.innerHTML = r.ok
    ? `<span class="st ok">${r.ms} ms</span>`
    : `<span class="st fail">недоступен</span>`;
}

async function pingProviderLoop(id) {
  if (!hostsPingOn) return;
  try {
    renderPing(await api("hosts_ping_one", id));
  } catch { /* тихо, повторим на следующем тике */ }
  if (hostsPingOn) hostsPingTimers[id] = setTimeout(() => pingProviderLoop(id), 1000);
}

function startHostsPing() {
  if (hostsPingOn) return;
  hostsPingOn = true;
  document.querySelectorAll("#hosts-providers .prov-row").forEach(row => pingProviderLoop(row.dataset.id));
}

function stopHostsPing() {
  hostsPingOn = false;
  Object.values(hostsPingTimers).forEach(t => clearTimeout(t));
  for (const k in hostsPingTimers) delete hostsPingTimers[k];
}

function selectProvider(id) {
  selectedProvider = id;
  document.querySelectorAll("#hosts-providers .prov-row").forEach(row => {
    const on = row.dataset.id === id;
    row.classList.toggle("selected", on);
    row.querySelector("input").checked = on;
  });
  renderLists();  // правая панель показывает списки выбранного провайдера
}

async function onHostsProviderClick(e) {
  const del = e.target.closest('[data-act="del"]');
  if (del) {
    const id = del.closest(".prov-row").dataset.id;
    const p = hostsProviders.find(x => x.id === id);
    const ok = await confirmModal({ title: "Удалить провайдера?", description: `Провайдер «${p?.name || id}» будет удалён.` });
    if (!ok) return;
    try {
      await api("hosts_delete_provider", id);
      if (selectedProvider === id) selectedProvider = null;
      await loadHosts();
      toast("Провайдер удалён.");
    } catch (err) {
      toast(err.message, true);
    }
    return;
  }
  const row = e.target.closest(".prov-row");
  if (row) selectProvider(row.dataset.id);
}

async function addHostsProvider() {
  const err = $("#hprov-add-error");
  err.textContent = "";
  try {
    await api("hosts_add_provider", $("#hprov-new-name").value, $("#hprov-new-doh").value,
      [$("#hprov-new-ip1").value, $("#hprov-new-ip2").value]);
    $("#hprov-new-name").value = $("#hprov-new-doh").value =
      $("#hprov-new-ip1").value = $("#hprov-new-ip2").value = "";
    $("#tab-hosts .add-prov").open = false;
    toast("Провайдер добавлен.");
    await loadHosts();
  } catch (e) {
    err.textContent = e.message;
  }
}

// --- dns tab ------------------------------------------------------------------

let dnsAdapters = [];
let dnsProviders = [];

function currentAdapter() {
  const idx = Number($("#dns-adapter").value);
  return dnsAdapters.find(a => a.index === idx);
}

// провайдер считается активным, если все текущие DNS адаптера принадлежат ему
function isActiveProvider(provider, adapter) {
  const cur = adapter?.dns || [];
  if (!cur.length) return false;
  const set = new Set(provider.servers);
  return cur.every(ip => set.has(ip));
}

// обновляет пометку «активен» и кнопки по выбранному адаптеру, не трогая пинг
function markActiveProvider() {
  const a = currentAdapter();
  document.querySelectorAll("#dns-providers .dns-row").forEach(row => {
    const p = dnsProviders.find(x => x.id === row.dataset.id);
    const active = a && isActiveProvider(p, a);
    row.classList.toggle("active", active);
    const badge = row.querySelector(".dns-active-badge");
    if (badge) badge.hidden = !active;
    const btn = row.querySelector('[data-act="use"]');
    if (btn) {
      btn.disabled = active;
      btn.textContent = active ? "Активен" : "Применить";
    }
  });
}

function renderDnsCurrent() {
  const a = currentAdapter();
  if (!a) {
    $("#dns-current").textContent = "";
    return;
  }
  const parts = [
    a.ipv4?.length ? `IP: ${a.ipv4.join(", ")}` : null,
    a.dns?.length ? `DNS: ${a.dns.join(", ")}` : "DNS: автоматически (DHCP)",
    a.speed ? `${a.speed}` : null,
  ].filter(Boolean);
  $("#dns-current").textContent = parts.join("  ·  ");
}

function adapterLabel(a) {
  // строка уходит в <option> — туда нельзя SVG/спан, только текстовый глиф
  const dot = a.status === "Up" ? "●" : "○";
  const kind = a.physical ? "" : " · вирт.";
  return `${dot} ${a.name} — ${a.desc}${kind}`;
}

async function loadDnsState() {
  const box = $("#dns-providers");
  let state;
  try {
    state = await api("dns_state");
  } catch (e) {
    box.innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`;
    return;
  }
  dnsAdapters = state.adapters;

  const prev = $("#dns-adapter").value;
  $("#dns-adapter").innerHTML = dnsAdapters.map(a =>
    `<option value="${a.index}">${esc(adapterLabel(a))}</option>`
  ).join("");
  // сохранить выбор пользователя между перерисовками; иначе первый (самый полезный)
  if (prev && dnsAdapters.some(a => String(a.index) === prev)) {
    $("#dns-adapter").value = prev;
  }
  renderDnsCurrent();

  dnsProviders = state.providers;
  box.className = "card card-wrap";
  box.innerHTML = dnsProviders.map(p => {
    const endpoints = [
      (p.ipv6 && p.ipv6.length) ? `IPv6 ${p.ipv6.map(esc).join(" · ")}` : "",
      p.doh ? `DoH ${esc(p.doh)}` : "",
      p.dot ? `DoT ${esc(p.dot)}` : "",
    ].filter(Boolean).join("  ·  ");
    return `
    <div class="dns-row" data-id="${p.id}">
      <span class="dns-name">
        <span class="dns-name-row">${esc(p.name)}
          ${p.servers && p.servers.length ? `<span class="badge proto">IPv4</span>` : ""}
          ${p.ipv6 && p.ipv6.length ? `<span class="badge proto">IPv6</span>` : ""}
          ${p.doh ? `<span class="badge crypto" title="DNS over HTTPS — «Применить» включит шифрование DoH в Windows.">DoH</span>` : ""}
          ${p.dot ? `<span class="badge crypto" title="DNS over TLS — используют браузеры; системный резолвер Windows DoT не применяет.">DoT</span>` : ""}
          ${p.unblock ? `<span class="badge unblock">обход</span>` : ""}
          ${p.filter ? `<span class="badge protect" title="Режет рекламу, трекеры, фишинг и вредоносные домены (набор зависит от провайдера).">защита</span>` : ""}
          <span class="badge on dns-active-badge" hidden>активен</span>
        </span>
        ${endpoints ? `<span class="dns-secure">${endpoints}</span>` : ""}
        <span class="dns-probe" data-probe hidden></span>
      </span>
      <span class="dns-servers">${p.servers.map(esc).join(" · ")}</span>
      <span class="dns-ping" data-ping></span>
      <button class="btn" data-act="probe" title="Проверить DNSSEC / обход / рекламу через этот DNS">Проба</button>
      <button class="btn primary" data-act="use">Применить</button>
      ${p.builtin ? "" : `<button class="btn-x" data-act="del" title="Удалить">×</button>`}
    </div>
  `;
  }).join("");
  markActiveProvider();
  if (dnsPingOn) { stopDnsPing(); startDnsPing(); }  // перецепить автопинг на новые строки
}

async function addDnsProvider() {
  const err = $("#dns-add-error");
  err.textContent = "";
  try {
    await api("dns_add_provider", $("#dns-new-name").value,
      [$("#dns-new-ip1").value, $("#dns-new-ip2").value],
      $("#dns-new-ip6").value, $("#dns-new-doh").value, $("#dns-new-dot").value,
      $("#dns-new-unblock").checked, $("#dns-new-filter").checked);
    $("#dns-new-name").value = $("#dns-new-ip1").value = $("#dns-new-ip2").value =
      $("#dns-new-ip6").value = $("#dns-new-doh").value = $("#dns-new-dot").value = "";
    $("#dns-new-unblock").checked = $("#dns-new-filter").checked = false;
    $("#tab-dns .add-prov").open = false;
    toast("DNS-провайдер добавлен.");
    await loadDnsState();
  } catch (e) {
    err.textContent = e.message;
  }
}

async function loadProbeConfig() {
  try {
    const c = await api("dns_probe_config");
    $("#probe-bypass").value = (c.bypass || []).join(" ");
    $("#probe-ad").value = c.ad || "";
  } catch { /* не критично — дефолты на бэке */ }
}

async function saveProbeConfig() {
  const err = $("#probe-error");
  err.textContent = "";
  try {
    const c = await api("dns_set_probe_config", $("#probe-bypass").value, $("#probe-ad").value);
    $("#probe-bypass").value = (c.bypass || []).join(" ");
    $("#probe-ad").value = c.ad || "";
    toast("Тест-домены пробы сохранены.");
  } catch (e) {
    err.textContent = e.message;
  }
}

// рендер ячейки пинга одного провайдера (общий для кнопки и автопинга)
function renderDnsPing(r) {
  const el = document.querySelector(`#dns-providers .dns-row[data-id="${r.id}"] [data-ping]`);
  if (!el) return;
  el.innerHTML = r.servers.map(s =>
    s.ok ? `<span class="st ok">${s.ms} ms</span>` : `<span class="st fail">—</span>`
  ).join(" / ");
}

// --- проба возможностей (DNSSEC / обход / реклама) ---
function probeMark(v) {
  return v === true ? `<span class="st ok">✓</span>`
       : v === false ? `<span class="st fail">✗</span>`
       : `<span class="st">—</span>`;
}

function renderProbe(r) {
  if (!r.reachable) return `<span class="st fail">сервер не ответил</span>`;
  const dom = Object.keys(r.unblock_detail || {}).join(", ");
  const bypassLbl = dom ? ` (${esc(dom)})` : "";
  return `проба: DNSSEC ${probeMark(r.dnssec)} · обход${bypassLbl} ${probeMark(r.unblock)}`
       + ` · реклама ${probeMark(r.filter)}`;
}

// автопинг: КАЖДЫЙ провайдер пингуется своим циклом раз в секунду, параллельно —
// медленный/флапающий не тормозит остальных (как на вкладке Hosts). Серверы одного
// провайдера внутри ping_one тоже летят параллельно.
let dnsPingOn = false;
const dnsPingTimers = {};

async function dnsPingProviderLoop(id) {
  if (!dnsPingOn) return;
  try { renderDnsPing(await api("dns_ping_one", id)); } catch { /* тихо, повторим */ }
  if (dnsPingOn) dnsPingTimers[id] = setTimeout(() => dnsPingProviderLoop(id), 1000);
}

function startDnsPing() {
  if (dnsPingOn) return;
  dnsPingOn = true;
  document.querySelectorAll("#dns-providers .dns-row").forEach(row => dnsPingProviderLoop(row.dataset.id));
}

function stopDnsPing() {
  dnsPingOn = false;
  Object.values(dnsPingTimers).forEach(t => clearTimeout(t));
  for (const k in dnsPingTimers) delete dnsPingTimers[k];
}

async function onDnsProviderAction(e) {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const row = btn.closest(".dns-row");
  const id = row.dataset.id;

  if (btn.dataset.act === "del") {
    const p = dnsProviders.find(x => x.id === id);
    const ok = await confirmModal({ title: "Удалить провайдера?", description: `Провайдер «${p?.name || id}» будет удалён.` });
    if (!ok) return;
    try {
      await api("dns_delete_provider", id);
      toast("Провайдер удалён.");
      await loadDnsState();
    } catch (err) {
      toast(err.message, true);
    }
    return;
  }

  if (btn.dataset.act === "probe") {
    const box = row.querySelector("[data-probe]");
    box.hidden = false;
    box.innerHTML = `<span class="probe-run">Проверяю…</span>`;
    btn.disabled = true;
    try {
      box.innerHTML = renderProbe(await api("dns_probe", id));
    } catch (err) {
      box.innerHTML = `<span class="st fail">${esc(err.message)}</span>`;
    } finally {
      btn.disabled = false;
    }
    return;
  }

  // act === "use"
  const a = currentAdapter();
  if (!a) return toast("Адаптер не выбран.", true);
  btn.disabled = true;
  try {
    const p = await api("dns_set", a.index, id);
    toast(`DNS → ${p.name}${p.encrypted ? " · шифрование (DoH) вкл" : ""}, кэш сброшен.`);
    await loadDnsState();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function onDnsReset() {
  const a = currentAdapter();
  if (!a) return toast("Адаптер не выбран.", true);
  try {
    await api("dns_reset", a.index);
    toast("DNS сброшен на DHCP.");
    await loadDnsState();
  } catch (err) {
    toast(err.message, true);
  }
}

// --- lists tab ----------------------------------------------------------------

let currentList = null;
let editorDirty = false;
let listsData = [];  // кэш последнего lists_all — читает контекстное меню

async function loadLists() {
  const side = $("#lists-files");
  let files;
  try {
    files = await api("lists_all");
  } catch (e) {
    side.innerHTML = `<div class="empty">Ошибка: ${esc(e.message)}</div>`;
    return;
  }
  listsData = files;
  renderListsFiles();
}

// рендер из кэша listsData — без похода в бэкенд, для мгновенного отклика тоглов
function renderListsFiles() {
  const side = $("#lists-files");
  side.innerHTML = listsData.map(f => {
    // метки «через что идёт список»: прокси (globe), hosts (server), winws (shield); только активные
    const badges = [
      f.proxy ? `<span class="lf-badge proxy" title="Идёт через прокси (sing-box)">${icon("globe")}</span>` : "",
      f.hosts ? `<span class="lf-badge hosts" title="Идёт через hosts">${icon("server")}</span>` : "",
      f.winws ? `<span class="lf-badge winws" title="Идёт через запрет (winws2)">${icon("shield")}</span>` : "",
    ].join("");
    return `
    <div class="list-file ${f.name === currentList ? "active" : ""}" data-name="${esc(f.name)}">
      <span class="fname">${esc(f.name)}</span>
      ${badges ? `<span class="lf-badges">${badges}</span>` : ""}
      <span class="fcount">${f.count}</span>
    </div>`;
  }).join("") || `<div class="empty">Списков нет</div>`;
}

async function openList(name) {
  await flushAutosave();  // сохранить хвост правок в предыдущем списке перед переключением
  $("#list-error").textContent = "";
  let text;
  try {
    text = await api("lists_read", name);
  } catch (e) {
    toast(e.message, true);
    return;
  }
  currentList = name;
  editorDirty = false;
  $("#editor-title").textContent = name + ".txt";
  const ta = $("#editor-text");
  ta.value = text;
  ta.disabled = false;
  setEditorStatus("");
  updateEditorMeta();
  document.querySelectorAll(".list-file").forEach(el =>
    el.classList.toggle("active", el.dataset.name === name)
  );
}

function closeEditor() {
  currentList = null;
  editorDirty = false;
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const ta = $("#editor-text");
  ta.value = "";
  ta.disabled = true;
  $("#editor-title").textContent = "Выбери список слева";
  $("#editor-meta").textContent = "";
  $("#list-error").textContent = "";
  setEditorStatus("");
}

function updateEditorMeta() {
  const lines = $("#editor-text").value.split("\n");
  const count = lines.filter(l => l.split("#")[0].trim()).length;
  $("#editor-meta").textContent = `${count} доменов`;
}

function setEditorStatus(state) {
  const el = $("#editor-status");
  el.className = "editor-status" + (state ? ` ${state}` : "");
  el.textContent = state === "saving" ? "Сохраняю…" : state === "saved" ? "Сохранено" : state === "error" ? "Ошибка сохранения" : "";
}

// автосохранение: правки летят в бэк сами, без отдельной кнопки «Сохранить»
let autosaveTimer = null;

function onEditorInput() {
  if (!currentList) return;
  editorDirty = true;
  updateEditorMeta();
  setEditorStatus("saving");
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(flushAutosave, 600);
}

async function flushAutosave() {
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  if (!editorDirty || !currentList) return;
  const name = currentList;
  const content = $("#editor-text").value;
  editorDirty = false;
  try {
    const info = await api("lists_save", name, content);
    const item = listsData.find(f => f.name === name);
    if (item) { item.count = info.count; renderListsFiles(); }
    if (currentList === name) setEditorStatus("saved");
  } catch (e) {
    editorDirty = true;  // не потерять правки, если сохранить не вышло
    if (currentList === name) {
      setEditorStatus("error");
      $("#list-error").textContent = e.message;
    }
  }
}

async function createList() {
  const input = $("#list-new-name");
  const name = input.value.trim();
  $("#list-error").textContent = "";
  if (!name) return;
  try {
    await api("lists_create", name);
    input.value = "";
    await loadLists();
    openList(name);
  } catch (e) {
    $("#list-error").textContent = e.message;
  }
}

async function deleteList(name) {
  const ok = await confirmModal({
    title: "Удалить список?",
    description: `Список «${name}» будет удалён без возможности восстановления.`,
    confirmLabel: "Удалить",
  });
  if (!ok) return;
  try {
    await api("lists_delete", name);
    toast(`Список ${name} удалён.`);
    if (currentList === name) closeEditor();
    await loadLists();
  } catch (e) {
    toast(e.message, true);
  }
}

async function renameList(name) {
  const next = await promptModal({
    title: "Переименовать список",
    description: `Новое имя для «${name}» (без .txt).`,
    value: name,
    confirmLabel: "Переименовать",
    validate: v => {
      if (!v) return "Имя не может быть пустым";
      if (!/^[A-Za-z0-9._-]+$/.test(v)) return "Только латиница, цифры, точка, дефис и подчёркивание";
      if (v !== name && listsData.some(f => f.name === v)) return `Список «${v}» уже существует`;
      return null;
    },
  });
  if (next === null || next === name) return;
  try {
    const info = await api("lists_rename", name, next);
    toast(`${name} → ${info.name}`);
    if (currentList === name) {
      currentList = info.name;
      $("#editor-title").textContent = info.name + ".txt";
    }
    await loadLists();
  } catch (e) {
    toast(e.message, true);
  }
}

function onListsClick(e) {
  const file = e.target.closest(".list-file");
  if (file) openList(file.dataset.name);
}

// --- контекстное меню списка: ПКМ → включить/выключить транспорт прямо тут ---

let listCtxTarget = null;

function closeListCtxMenu() {
  $("#list-ctx-menu").classList.remove("show");
  listCtxTarget = null;
}

function onListsContext(e) {
  const file = e.target.closest(".list-file");
  if (!file) return closeListCtxMenu();
  e.preventDefault();
  const item = listsData.find(f => f.name === file.dataset.name);
  if (!item) return;
  listCtxTarget = item.name;

  const toggleRow = (transport, iconName, label, disabled, hint) => `
    <div class="ctx-item ${disabled ? "disabled" : ""}" data-transport="${disabled ? "" : transport}" title="${esc(hint || "")}">
      ${icon(iconName)}<span class="ctx-label">${label}</span>
      <span class="switch"><input type="checkbox" ${item[transport] ? "checked" : ""} disabled tabindex="-1"><span class="slider"></span></span>
    </div>`;
  const actionRow = (action, iconName, label, danger) => `
    <div class="ctx-item ${danger ? "danger" : ""}" data-action="${action}">
      ${icon(iconName)}<span class="ctx-label">${label}</span>
    </div>`;

  const menu = $("#list-ctx-menu");
  menu.innerHTML =
    `<div class="ctx-menu-title">${esc(item.name)}.txt</div>` +
    toggleRow("proxy", "globe", "Прокси (VPN)", false) +
    toggleRow("winws", "shield", "Запрет (winws)", false) +
    toggleRow("hosts", "server", "Hosts", true, "Hosts привязывается к DNS-провайдеру — выбери его во вкладке Hosts") +
    `<div class="ctx-sep"></div>` +
    actionRow("rename", "pencil", "Переименовать", false) +
    actionRow("delete", "trash", "Удалить", true);

  menu.classList.add("show");
  const x = Math.min(e.clientX, window.innerWidth - menu.offsetWidth - 8);
  const y = Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 8);
  menu.style.left = `${Math.max(4, x)}px`;
  menu.style.top = `${Math.max(4, y)}px`;
}

function onListCtxMenuClick(e) {
  const row = e.target.closest(".ctx-item");
  if (!row || row.classList.contains("disabled") || !listCtxTarget) return;
  const name = listCtxTarget;
  if (row.dataset.transport) {
    toggleListTransport(name, row.dataset.transport);
  } else if (row.dataset.action === "rename") {
    closeListCtxMenu();
    renameList(name);
  } else if (row.dataset.action === "delete") {
    closeListCtxMenu();
    deleteList(name);
  }
}

function toggleListTransport(name, transport) {
  const item = listsData.find(f => f.name === name);
  closeListCtxMenu();
  if (!item) return;
  const makeActive = !item[transport];
  item[transport] = makeActive;  // оптимистично: бейдж меняется сразу, не ждём рестарта движка
  renderListsFiles();
  const next = listsData.filter(f => f[transport]).map(f => f.name);
  const apiMethod = transport === "proxy" ? "proxy_set_lists" : "winws_set_lists";
  const label = transport === "proxy" ? "прокси" : "запрет";
  toast(`${name}: ${label} ${makeActive ? "включён" : "выключен"}.`);
  // применяется в фоне (может перезапустить движок) — если не взлетит, смотреть в логе нужной вкладки
  api(apiMethod, next).catch(() => {});
}

// --- cheburcheck: проверка блокировок РКН (своя вкладка) ---
const CHEBUR_LABELS = { blocked: "БЛОК", free: "свободен", rate: "лимит", error: "ошибка" };
let cheburExpected = 0, cheburDone = 0, cheburBlocked = 0, cheburRunning = false;

async function loadBlocks() {
  // статус реестра в баннере
  const box = $("#chebur-status");
  try {
    const s = await api("chebur_status");
    const upd = s.last_update ? new Date(s.last_update).toLocaleString("ru-RU") : "?";
    const cnt = s.domain_count ? s.domain_count.toLocaleString("ru-RU") : "?";
    const v4 = s.v4_count ? `, ${Math.round(s.v4_count / 1e6)} млн IPv4` : "";
    box.className = "hosts-status on";
    box.innerHTML = `cheburcheck v${esc(s.version || "?")} · реестр РКН: ${cnt} доменов${v4}, обновлён ${esc(upd)}.`;
  } catch {
    box.className = "hosts-status off";
    box.textContent = "cheburcheck недоступен — проверка блокировок сейчас офлайн.";
  }
  // выпадашки со списками — общие для обеих проверок
  try {
    const files = await api("lists_all");
    const opts = files.map(f =>
      `<option value="${esc(f.name)}">${esc(f.name)} (${f.count})</option>`).join("");
    $("#chebur-list").innerHTML = opts;
    $("#block-list").innerHTML = opts;
  } catch { /* списки подтянутся на следующем заходе */ }
}

function cheburResetResults(label) {
  const box = $("#chebur-results");
  box.hidden = false;
  box.innerHTML = `<div class="check-summary" id="chebur-summary">${label}</div>`;
}

function cheburDate(s) { return s ? String(s).slice(0, 10) : ""; }  // ISO → YYYY-MM-DD

// строка деталей под доменом: причина блокировки + гео + популярность + PTR (что есть)
function cheburMeta(r) {
  if (r.status === "rate") return "не проверен — лимит запросов";
  if (r.status === "error") return "не проверен — сетевая ошибка";
  const bits = [];
  if (r.status === "blocked") {
    if (r.rkn_domain) bits.push("реестр РКН");
    if (r.subnets?.length) bits.push(`подсети: ${r.subnets.join(", ")}`);
    if (r.cdn?.length) bits.push(`CDN: ${r.cdn.join(", ")}`);
    if (!bits.length) bits.push("заблокирован");
  } else {
    bits.push("в реестрах не найден");
  }
  if (r.geo?.org) bits.push(r.geo.asn ? `${r.geo.org} (${r.geo.asn})` : r.geo.org);
  else if (r.geo?.asn) bits.push(r.geo.asn);
  if (r.rank) bits.push(`популярность #${r.rank}`);
  if (r.last_ok) bits.push(`посл. доступ ${cheburDate(r.last_ok)}`);
  if (r.ptr?.length) bits.push(`PTR: ${r.ptr.join(", ")}`);
  return bits.join(" · ");
}

function cheburRow(r) {
  const stClass = r.blocked ? "fail" : (r.status === "free" ? "ok" : "tcp");
  const chips = [];
  if (r.type) chips.push(`<span class="chebur-chip">${esc(r.type)}</span>`);
  if (r.geo?.country) chips.push(`<span class="chebur-chip geo">${esc(r.geo.country)}</span>`);
  const meta = cheburMeta(r);
  // полный список IP — в подсказке по наведению (их бывает много, в строку не лезут)
  const ipTitle = r.ips?.length ? ` title="IP: ${esc(r.ips.join(", "))}"` : "";
  return `
    <div class="chebur-row"${ipTitle}>
      <div class="chebur-row-main">
        <span class="st ${stClass}">${CHEBUR_LABELS[r.status] || r.status}</span>
        <span class="hostname">${esc(r.target)}</span>
        ${chips.length ? `<span class="chebur-chips">${chips.join("")}</span>` : ""}
      </div>
      ${meta ? `<div class="chebur-meta">${esc(meta)}</div>` : ""}
    </div>`;
}

async function checkOneDomain() {
  const domain = $("#chebur-domain").value.trim();
  $("#chebur-error").textContent = "";
  if (!domain) return;
  cheburResetResults("Проверяю…");
  try {
    const r = await api("chebur_check_one", domain);
    $("#chebur-results").innerHTML = "";
    $("#chebur-results").insertAdjacentHTML("beforeend", cheburRow(r));
  } catch (e) {
    $("#chebur-error").textContent = e.message;
    $("#chebur-results").hidden = true;
  }
}

async function checkListBlocks() {
  if (cheburRunning) return;
  const name = $("#chebur-list").value;
  if (!name) return;
  $("#chebur-error").textContent = "";
  cheburResetResults("Запускаю проверку…");
  $("#chebur-list-btn").disabled = true;
  try {
    const info = await api("chebur_check_start", name);
    cheburExpected = info.total; cheburDone = 0; cheburBlocked = 0; cheburRunning = true;
    $("#chebur-summary").textContent = `Проверяю 0/${cheburExpected}…`;
  } catch (e) {
    $("#chebur-error").textContent = e.message;
    $("#chebur-results").hidden = true;
    $("#chebur-list-btn").disabled = false;
  }
}

window.cheburResult = function (r) {
  cheburDone++;
  if (r.blocked) cheburBlocked++;
  $("#chebur-results").insertAdjacentHTML("beforeend", cheburRow(r));
  const s = $("#chebur-summary");
  if (s) s.textContent = `Проверяю ${cheburDone}/${cheburExpected}…`;
};

window.cheburDone = function () {
  cheburRunning = false;
  $("#chebur-list-btn").disabled = false;
  const s = $("#chebur-summary");
  if (s) s.innerHTML = `Заблокировано: <b>${cheburBlocked}/${cheburExpected}</b>
    <span class="ms">(БЛОК — домен в реестре РКН или в заблокированной подсети)</span>`;
};

// --- blockcheck: локальная достижимость с этой машины (тот же таб) ---
const BLOCK_LABELS = { ok: "ok", challenge: "CLOUDFLARE", denied: "ОТКАЗ", blocked: "БЛОК", dns: "нет DNS", error: "ошибка" };
let blockExpected = 0, blockDoneN = 0, blockOk = 0, blockRunning = false;

function blockResetResults(label) {
  const box = $("#block-results");
  box.hidden = false;
  box.innerHTML = `<div class="check-summary" id="block-summary">${label}</div>`;
}

const BLOCK_CLASSES = { ok: "ok", challenge: "cf", denied: "fail", blocked: "fail" };

function blockRow(r) {
  const cls = BLOCK_CLASSES[r.status] || "tcp";
  const detail = [r.ip, r.reason, r.ms ? `${r.ms} мс` : null].filter(Boolean).join(" · ");
  return `
    <div class="check-row">
      <span class="st ${cls}">${BLOCK_LABELS[r.status] || r.status}</span>
      <span class="hostname">${esc(r.target)}</span>
      <span class="ip">${esc(detail)}</span>
    </div>`;
}

async function checkOneReach() {
  const domain = $("#block-domain").value.trim();
  $("#block-error").textContent = "";
  if (!domain) return;
  blockResetResults("Проверяю…");
  try {
    const r = await api("block_check_one", domain);
    $("#block-results").innerHTML = "";
    $("#block-results").insertAdjacentHTML("beforeend", blockRow(r));
  } catch (e) {
    $("#block-error").textContent = e.message;
    $("#block-results").hidden = true;
  }
}

async function checkListReach() {
  if (blockRunning) return;
  const name = $("#block-list").value;
  if (!name) return;
  $("#block-error").textContent = "";
  blockResetResults("Запускаю проверку…");
  $("#block-list-btn").disabled = true;
  try {
    const info = await api("block_check_start", name);
    blockExpected = info.total; blockDoneN = 0; blockOk = 0; blockRunning = true;
    $("#block-summary").textContent = `Проверяю 0/${blockExpected}…`;
  } catch (e) {
    $("#block-error").textContent = e.message;
    $("#block-results").hidden = true;
    $("#block-list-btn").disabled = false;
  }
}

window.blockResult = function (r) {
  blockDoneN++;
  if (r.status === "ok") blockOk++;
  $("#block-results").insertAdjacentHTML("beforeend", blockRow(r));
  const s = $("#block-summary");
  if (s) s.textContent = `Проверяю ${blockDoneN}/${blockExpected}…`;
};

window.blockDone = function () {
  blockRunning = false;
  $("#block-list-btn").disabled = false;
  const s = $("#block-summary");
  if (s) s.innerHTML = `Достучались: <b>${blockOk}/${blockExpected}</b>
    <span class="ms">(CF — пройдёт сам в браузере; ОТКАЗ — бан на стороне сайта, не DPI;
    БЛОК — RST/таймаут; нет DNS — не резолвится)</span>`;
};

// --- telegram proxy tab ---------------------------------------------------------

let tgState = null;
let tgStatsTimer = null;

function tgFillForm() {
  $("#tg-host").value = tgState.host;
  $("#tg-port").value = tgState.port;
  $("#tg-secret").value = tgState.secret;
  $("#tg-autostart").checked = !!tgState.autostart;
}

function renderTgStatus() {
  const box = $("#tg-status");
  box.className = "hosts-status " + (tgState.running ? "on" : "off");
  box.textContent = tgState.running
    ? `✓ Работает на ${tgState.host}:${tgState.port} — добавь прокси в Telegram кнопкой ниже.`
    : "Прокси остановлен.";
  const toggle = $("#tg-toggle-btn");
  toggle.textContent = tgState.running ? "Остановить" : "Запустить";
  toggle.disabled = false;
  $("#tg-open-btn").disabled = $("#tg-copy-btn").disabled = !tgState.link;
  $("#tg-error").textContent = tgState.error || "";
  if (tgState.version && !$("#tg-version").dataset.update) {
    $("#tg-version").textContent = `tg-ws-proxy v${tgState.version}`;
  }
  if (!tgState.running) $("#tg-stats").hidden = true;
}

async function loadTgProxy() {
  try {
    tgState = await api("tg_state");
  } catch (e) {
    $("#tg-error").textContent = e.message;
    return;
  }
  renderTgStatus();
  tgFillForm();
  loadTgLog();
}

// раз за запуск сверяем версию сабмодуля с последним релизом на GitHub
async function tgCheckUpdate() {
  try {
    const u = await api("tg_check_update");
    if (!u.has_update) return;
    const el = $("#tg-version");
    el.dataset.update = "1";
    el.innerHTML = `tg-ws-proxy v${esc(u.current)} ·
      <a href="${esc(u.url)}" target="_blank">доступна v${esc(u.latest)}</a>`;
  } catch { /* офлайн или лимит GitHub API — молчим */ }
}

async function tgToggle() {
  const btn = $("#tg-toggle-btn");
  btn.disabled = true;
  try {
    tgState = await api(tgState?.running ? "tg_stop" : "tg_start");
    toast(tgState.running ? "Прокси запущен." : "Прокси остановлен.");
  } catch (e) {
    toast(e.message, true);
    await loadTgProxy();
    return;
  }
  renderTgStatus();
  if (tgState.running) startTgStats();
}

// изменение любого контрола сразу пишется в state.json (как в «Настройках»)
async function tgApply() {
  $("#tg-error").textContent = "";
  try {
    tgState = await api("tg_set_config", $("#tg-host").value,
      Number($("#tg-port").value), $("#tg-secret").value, $("#tg-autostart").checked);
    tgFillForm();
    renderTgStatus();
    toast(tgState.running ? "Сохранено, прокси перезапущен." : "Сохранено.");
  } catch (e) {
    $("#tg-error").textContent = e.message;
    tgFillForm();  // откатить поля к фактическому состоянию
  }
}

async function tgRegenSecret() {
  try {
    tgState = await api("tg_regen_secret");
    tgFillForm();
    renderTgStatus();
    toast(tgState.running ? "Новый секрет, прокси перезапущен." : "Новый секрет сгенерирован.");
  } catch (e) {
    toast(e.message, true);
  }
}

async function tgCopyLink() {
  if (!tgState?.link) return;
  try {
    await navigator.clipboard.writeText(tgState.link);
    toast("Ссылка скопирована — вставь в Telegram.");
  } catch {
    toast("Не удалось скопировать.", true);
  }
}

async function tgOpenLink() {
  try {
    await api("tg_open_link");
    toast("Открываю в Telegram…");
  } catch (e) {
    toast(e.message, true);
  }
}

// живая статистика, только пока открыта вкладка Прокси и прокси запущен
async function tgStatsLoop() {
  if (!tgState?.running) {
    $("#tg-stats").hidden = true;
    tgStatsTimer = null;
    return;
  }
  try {
    const s = await api("tg_stats");
    const el = $("#tg-stats");
    el.hidden = false;
    el.textContent = `Соединения: ${s.active} активных / ${s.total} всего · ` +
      `WS: ${s.ws} · TCP-фолбэк: ${s.tcp_fallback} · CF: ${s.cfproxy} · ` +
      `↑ ${s.up} · ↓ ${s.down}`;
  } catch { /* тихо, повторим на следующем тике */ }
  tgStatsTimer = setTimeout(tgStatsLoop, 2000);
}

function startTgStats() {
  if (tgStatsTimer) return;
  tgStatsLoop();
}

function stopTgStats() {
  clearTimeout(tgStatsTimer);
  tgStatsTimer = null;
}

let tgLogTimer = null, tgLogOffset = 0, tgLogBusy = false;

async function loadTgLog() {
  if (tgLogBusy) return;
  tgLogBusy = true;
  try {
    const r = await api("tg_log", tgLogOffset);
    if (r && typeof r.offset === "number") tgLogOffset = r.offset;
    applyLogChunk($("#tg-log"), r, "— пусто (tg-прокси ещё не запускался) —");
  } catch (e) { /* молча */ } finally { tgLogBusy = false; }
}

function tgLogAuto(on) {
  clearInterval(tgLogTimer);
  tgLogTimer = on ? setInterval(loadTgLog, 300) : null;
}

// --- strategies tab (zapret2 / winws2) ----------------------------------------

let winwsState = null;
let winwsSelected = null;

async function loadStrategies() {
  let st;
  try {
    st = await api("winws_state");
  } catch (e) {
    $("#winws-error").textContent = e.message;
    return;
  }
  winwsState = st;
  // выбор: запущенная > выбранная в этой сессии > сохранённая с прошлого раза > первая
  winwsSelected = st.current || winwsSelected || st.last_strategy || st.strategies[0]?.id || null;

  $("#winws-list").innerHTML = st.strategies.map(s => `
    <label class="winws-row ${s.id === winwsSelected ? "selected" : ""} ${s.id === st.current ? "running" : ""}" data-id="${esc(s.id)}">
      <input type="radio" name="winws" ${s.id === winwsSelected ? "checked" : ""}>
      <div class="winws-info">
        <div class="winws-name">${esc(s.name)} ${s.id === st.current ? '<span class="badge on">работает</span>' : ""}</div>
        <div class="winws-desc">${esc(s.desc || "")}</div>
      </div>
    </label>`).join("") || `<div class="empty">Стратегий нет в strategies/.</div>`;

  if (st.strategies.length) renderWinwsStatus();
  else $("#winws-status").textContent = "Стратегии не найдены.";
  loadWinwsLog();
}

let winwsLogTimer = null, winwsLogOffset = 0, winwsLogBusy = false;

async function loadWinwsLog() {
  if (winwsLogBusy) return;
  winwsLogBusy = true;
  try {
    const r = await api("winws_log", winwsLogOffset);
    if (r && typeof r.offset === "number") winwsLogOffset = r.offset;
    applyLogChunk($("#winws-log"), r, "— пусто (winws2 ещё не запускался) —");
  } catch (e) { /* молча */ } finally { winwsLogBusy = false; }
}

function winwsLogAuto(on) {
  clearInterval(winwsLogTimer);
  winwsLogTimer = on ? setInterval(loadWinwsLog, 300) : null;
}

function renderWinwsStatus() {
  const box = $("#winws-status");
  // драйвер WinDivert живёт отдельной службой: может висеть даже когда winws2 мёртв
  const wdLingers = !winwsState.running && winwsState.windivert === "RUNNING";
  box.className = "hosts-status " + (winwsState.running || wdLingers ? "on" : "off");
  const name = winwsState.strategies.find(s => s.id === winwsState.current)?.name;
  if (winwsState.external) {
    box.textContent = "✓ zapret2 уже работает (запущен ранее, вне этой сессии). Стратегия неизвестна — нажми «Остановить», чтобы выключить.";
  } else if (winwsState.running) {
    box.textContent = `✓ zapret2 работает · стратегия «${name}». Трафик идёт через winws2.`;
  } else if (wdLingers) {
    box.textContent = "winws2 остановлен, но драйвер WinDivert ещё активен. Нажми «Выгрузить WinDivert», чтобы убрать его.";
  } else {
    box.textContent = "zapret2 остановлен. Выбери стратегию и нажми «Запустить».";
  }
  const btn = $("#winws-toggle-btn");
  // переключение между стратегиями — кликом по строке (см. onWinwsSelect), не кнопкой
  btn.textContent = wdLingers ? "Выгрузить WinDivert" : winwsState.running ? "Остановить" : "Запустить";
  // остановить/выгрузить можно всегда, запустить — только когда выбрана стратегия
  btn.disabled = (winwsState.running || wdLingers) ? false : !winwsSelected;
  const wd = winwsState.windivert;
  const wdTxt = wd === "RUNNING" ? "WinDivert: активен" : wd === "STOPPED" ? "WinDivert: остановлен" : "WinDivert: не загружен";
  $("#winws-version").textContent = [winwsState.version ? `zapret2 ${winwsState.version}` : "", wdTxt].filter(Boolean).join(" · ");
  $("#winws-error").textContent = winwsState.error || "";
  $("#winws-autostart").checked = !!winwsState.autostart;
  renderWinwsLists();
}

function renderWinwsLists() {
  const box = $("#winws-lists");
  const all = winwsState.all_lists || [];
  if (!all.length) { box.innerHTML = `<div class="empty">Списков нет — добавь во вкладке «Списки».</div>`; return; }
  const sel = new Set(winwsState.lists || []);
  box.innerHTML = all.map(n => `
    <label class="list-check">
      <input type="checkbox" value="${esc(n)}" ${sel.has(n) ? "checked" : ""}>
      <span class="lc-name">${esc(n)}</span>
    </label>`).join("");
}

async function onWinwsListToggle(e) {
  if (!e.target.closest("input[type=checkbox]")) return;
  const names = [...document.querySelectorAll("#winws-lists input:checked")].map(c => c.value);
  try { winwsState = { ...winwsState, ...await api("winws_set_lists", names) }; renderWinwsStatus(); }
  catch (err) { $("#winws-error").textContent = err.message; renderWinwsLists(); }
}

async function setWinwsAutostart(v) {
  try { winwsState = { ...winwsState, ...await api("winws_set_autostart", v) }; }
  catch (e) { toast(e.message, true); }
}

async function onWinwsSelect(e) {
  const row = e.target.closest(".winws-row");
  if (!row) return;
  const id = row.dataset.id;
  winwsSelected = id;
  document.querySelectorAll("#winws-list .winws-row").forEach(r => {
    const on = r.dataset.id === id;
    r.classList.toggle("selected", on);
    r.querySelector("input").checked = on;
  });
  // на ходу — клик по другой стратегии сразу переключает (перезапуск с выбранной)
  if (winwsState?.running && id !== winwsState.current) {
    $("#winws-error").textContent = "";
    try {
      winwsState = { ...winwsState, ...await api("winws_start", id) };
      toast("Стратегия переключена.");
    } catch (err) {
      $("#winws-error").textContent = err.message;
    }
    await loadStrategies();
  } else {
    renderWinwsStatus();
  }
}

async function winwsToggle() {
  const btn = $("#winws-toggle-btn");
  btn.disabled = true;
  $("#winws-error").textContent = "";
  const wdLingers = !winwsState.running && winwsState.windivert === "RUNNING";
  try {
    if (winwsState.running || wdLingers) {
      winwsState = { ...winwsState, ...await api("winws_stop") };
      toast(wdLingers ? "Драйвер WinDivert выгружен." : "zapret2 остановлен.");
    } else {
      winwsState = { ...winwsState, ...await api("winws_start", winwsSelected) };
      toast("zapret2 запущен.");
    }
  } catch (e) {
    $("#winws-error").textContent = e.message;
  }
  await loadStrategies();
}

// --- winws фильтры (game / ipset) ---------------------------------------------

async function loadFilters() {
  let f;
  try { f = await api("filters_state"); } catch { return; }
  document.querySelectorAll("#game-seg button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === f.game));
  document.querySelectorAll("#ipset-seg button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === f.ipset));
  $("#ipset-info").textContent = f.ipset === "loaded" ? `${f.ipset_count} подсетей`
    : (f.ipset_stored ? `${f.ipset_stored} в запасе` : "");
  renderFakeSlots(f.fakes);
}

// ACTIVE_*-слоты: в каждом лежит копия одного из блобов, выбор — селектом
function renderFakeSlots(fakes) {
  const box = $("#fake-slots");
  if (!box) return;
  if (!fakes || !fakes.candidates?.length) { box.innerHTML = ""; return; }
  box.innerHTML = Object.entries(fakes.slots).map(([slot, s]) => {
    // «свой файл» — блоб в слоте не совпал ни с одним кандидатом (подложен руками)
    const custom = s.present && !s.current
      ? `<option value="" selected>свой файл</option>` : "";
    const opts = fakes.candidates.map(name =>
      `<option value="${esc(name)}"${name === s.current ? " selected" : ""}>${esc(name)}</option>`
    ).join("");
    return `<label class="fake-slot"><span>${esc(s.label)}</span>
      <select data-fake-slot="${esc(slot)}">${custom}${opts}</select></label>`;
  }).join("");
}

async function setFake(slot, name) {
  $("#filters-error").textContent = "";
  if (!name) return;  // выбрали псевдо-пункт «свой файл» — менять нечего
  try {
    await api("fake_set", slot, name);
    await loadFilters();
    await applyRunningChange("Фейк");
  } catch (e) {
    $("#filters-error").textContent = e.message;
    await loadFilters();  // вернуть селект к факту
  }
}

// настройка уже записана; если наша стратегия запущена — перезапустим, чтобы применить
async function applyRunningChange(what) {
  if (!winwsState?.running) return;
  if (winwsState.external || !winwsState.current) {
    toast(`Перезапусти стратегию, чтобы применить ${what} (внешний процесс).`);
    return;
  }
  try {
    winwsState = { ...winwsState, ...await api("winws_start", winwsState.current) };
    toast(`${what} применён — стратегия перезапущена.`);
    await loadStrategies();
  } catch (e) { $("#filters-error").textContent = e.message; }
}

async function setGameFilter(mode) {
  $("#filters-error").textContent = "";
  try {
    await api("game_filter_set", mode);
    await loadFilters();
    await applyRunningChange("Game-фильтр");
  } catch (e) { $("#filters-error").textContent = e.message; }
}

async function setIpset(mode) {
  $("#filters-error").textContent = "";
  try {
    await api("ipset_set", mode);
    await loadFilters();
    await applyRunningChange("IPSet");
  } catch (e) { $("#filters-error").textContent = e.message; }
}

async function updateIpset() {
  const btn = $("#ipset-update-btn");
  btn.disabled = true; btn.textContent = "Качаю…";
  $("#filters-error").textContent = "";
  try {
    const r = await api("ipset_update");
    await loadFilters();
    toast(`Список обновлён: ${r.downloaded} подсетей (в запасе).`);
    if (r.state === "loaded") await applyRunningChange("IPSet");  // перезапуск только если «Список» активен
  } catch (e) {
    $("#filters-error").textContent = e.message;
  } finally {
    btn.disabled = false; btn.textContent = "Обновить список";
  }
}

// --- settings tab -------------------------------------------------------------

async function loadSettings() {
  try {
    const cfg = await api("config_read");
    $("#set-interface").value = cfg.interface || "ui";
    $("#set-ui-backend").value = cfg.ui_backend || "pyside6";
    $("#set-elevate").checked = cfg.auto_elevate !== false;
    $("#config-error").textContent = "";
  } catch (e) {
    $("#config-error").textContent = e.message;
  }
  try {
    const a = await api("autostart_get");  // состояние читаем отдельно — это задача планировщика, не config.json
    $("#set-autostart").checked = !!a.enabled;
    $("#set-autostart").disabled = !a.supported;
  } catch { /* не критично — оставим тумблер как есть */ }
}

async function setAutostart(on) {
  $("#config-error").textContent = "";
  try {
    const a = await api("autostart_set", on);
    $("#set-autostart").checked = !!a.enabled;
    toast(a.enabled ? "Автозапуск с Windows включён." : "Автозапуск с Windows выключен.");
  } catch (e) {
    $("#set-autostart").checked = !on;  // откат тумблера при ошибке (нет прав и т.п.)
    $("#config-error").textContent = e.message;
    toast(e.message, true);
  }
}

// изменение контрола сразу пишется в config.json
async function setSetting(key, value) {
  $("#config-error").textContent = "";
  try {
    await api("config_set", key, value);
    toast("Сохранено.");
  } catch (e) {
    $("#config-error").textContent = e.message;
    loadSettings();  // откатить контрол к фактическому состоянию
  }
}

// --- источники и обновления (Настройки) -------------------------------------

let sourcesState = [];
let sourcesChecked = false;  // прогоняли ли сверку с GitHub в этой сессии
let isAdmin = false;         // права администратора (для дашборда)

async function loadSources() {
  try {
    sourcesState = await api("upstream_versions");
    renderSources();
    renderDashFoot();
  } catch (e) { $("#src-error").textContent = e.message; }
}

// что сейчас делается с источником: имя -> "check" | "update".
// Строка рисуется из общего состояния, поэтому «занятость» держим рядом с ним,
// а не на самой кнопке: любая перерисовка кнопку бы обнулила.
const srcBusy = new Map();

function renderSources() {
  // одни и те же данные рисуем во все контейнеры .src-list (Настройки + Дашборд)
  const html = !sourcesState.length
    ? `<div class="empty">Источников нет.</div>`
    : sourcesState.map(s => {
        const busy = srcBusy.get(s.name);
        let right;
        if (busy) right = `<span class="src-badge info">${busy === "update" ? "Обновляю…" : "Проверяю…"}</span>`;
        else if (s.error) right = `<span class="src-warn">${esc(s.error)}</span>`;
        else if (s.note) right = `<span class="src-badge info">${esc(s.note)}</span>`;  // онлайн-сервис: дата реестра
        else if (s.latest === undefined) right = `<span class="src-cur">не проверено</span>`;  // только локальная версия
        else if (s.latest === null) right = `<span class="src-cur">${esc(s.version || s.current || "—")}</span>`;
        else if (s.update) right = `<span class="src-badge update">обновление: ${esc(s.latest)}</span>`;
        else right = `<span class="src-badge ok">актуально</span>`;
        const cur = s.version || s.current || "—";
        // кнопка «Обновить» показывается только там, где обновление реально есть
        // кому применить: git-источники рядом с нами. Для пиннутых (sing-box,
        // шрифты), Python и онлайн-сервиса она неактивна с пояснением — иначе
        // непонятно, почему у одной строки кнопка есть, а у соседней нет.
        // слот держится всегда — иначе кнопки «Проверить» у соседних строк
        // разъезжаются по горизонтали в зависимости от того, есть обновление или нет
        const upd = !s.update || busy
          ? `<span class="src-slot"></span>`
          : (s.updatable
              ? `<button class="btn primary btn-sm" data-act="update">Обновить</button>`
              : `<button class="btn btn-sm" data-act="update" disabled
                   title="Версия пиннута в коде — обновляется правкой исходников">Обновить</button>`);
        return `<div class="src-row" data-name="${esc(s.name)}">
          <div class="src-info">
            <a href="${esc(s.repo)}" target="_blank" class="src-name">${esc(s.name)}</a>
            <span class="src-ver">${esc(cur)}</span>
          </div>
          <div class="src-actions">
            ${right}
            <button class="btn btn-sm" data-act="check" title="Проверить только этот источник"${busy ? " disabled" : ""}>Проверить</button>
            ${upd}
          </div>
        </div>`;
      }).join("");
  document.querySelectorAll(".src-list").forEach(box => box.innerHTML = html);
}

// подменить один источник в общем состоянии (ответ пришёл по одной строке)
function mergeSource(s) {
  const i = sourcesState.findIndex(x => x.name === s.name);
  if (i >= 0) sourcesState[i] = s; else sourcesState.push(s);
}

async function onSourceAction(e) {
  const btn = e.target.closest(".src-row [data-act]");
  if (!btn || btn.disabled) return;
  const name = btn.closest(".src-row").dataset.name;
  if (btn.dataset.act === "check") await checkOneSource(name);
  else await updateSource(name);
}

async function checkOneSource(name) {
  if (srcBusy.has(name)) return;
  srcBusy.set(name, "check");
  renderSources();
  $("#src-error").textContent = "";
  try {
    const s = await api("upstream_check_one", name);
    mergeSource(s);
    toast(s.error ? `${name}: ${s.error}`
      : s.update ? `${name}: есть обновление — ${s.latest}.`
      : `${name}: актуально.`, !!s.error);
  } catch (e) { $("#src-error").textContent = e.message; toast(e.message, true); }
  finally { srcBusy.delete(name); renderSources(); renderDashFoot(); }
}

async function updateSource(name, quiet) {
  if (srcBusy.has(name)) return false;
  srcBusy.set(name, "update");
  renderSources();
  $("#src-error").textContent = "";
  let ok = false;
  try {
    const s = await api("upstream_update", name);
    mergeSource(s);
    ok = true;
    if (!quiet) toast(`${name}: ${s.note || "обновлено"}.`);
  } catch (e) {
    $("#src-error").textContent = `${name}: ${e.message}`;
    if (!quiet) toast(e.message, true);
  } finally { srcBusy.delete(name); renderSources(); renderDashFoot(); }
  return ok;
}

// результат по одному источнику прилетает из Python по мере готовности
// (см. ui/api.py: upstream_check_updates) — строка перерисовывается сразу,
// не дожидаясь самой медленной сверки
window.srcChecked = function (s) {
  if (srcBusy.get(s.name) === "check") srcBusy.delete(s.name);
  mergeSource(s);
  renderSources();
  renderDashFoot();
};

async function checkSourceUpdates(btn) {
  btn = btn && btn.tagName ? btn : $("#src-check-btn");
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Проверяю…";
  $("#src-error").textContent = "";
  // все строки сразу в «Проверяю…», дальше каждая гаснет своим srcChecked
  sourcesState.forEach(s => { if (!srcBusy.has(s.name)) srcBusy.set(s.name, "check"); });
  renderSources();
  try {
    sourcesState = await api("upstream_check_updates");
    sourcesChecked = true;
    const n = sourcesState.filter(s => s.update).length;
    toast(n ? `Есть обновления: ${n}.` : "Всё актуально.");
  } catch (e) { $("#src-error").textContent = e.message; }
  finally {
    sourcesState.forEach(s => { if (srcBusy.get(s.name) === "check") srcBusy.delete(s.name); });
    renderSources();
    renderDashFoot();
  }
  btn.disabled = false; btn.textContent = label;
}

// «Обновить всё»: без свежей сверки обновлять нечего — сперва проверяем, потом
// тянем по очереди (параллельный git по одному и тому же репозиторию мешает сам себе).
async function updateAllSources() {
  const btn = $("#src-update-btn");
  btn.disabled = true;
  const label = btn.textContent;
  try {
    if (!sourcesChecked) {
      btn.textContent = "Проверяю…";
      sourcesState = await api("upstream_check_updates");
      sourcesChecked = true;
      renderSources();
    }
    const names = sourcesState.filter(s => s.update && s.updatable).map(s => s.name);
    if (!names.length) return toast("Обновлять нечего — всё актуально.");
    btn.textContent = "Обновляю…";
    let done = 0;
    for (const name of names) if (await updateSource(name, true)) done++;
    toast(done === names.length
      ? `Обновлено источников: ${done}.`
      : `Обновлено ${done} из ${names.length}, остальное — в ошибке ниже.`,
      done !== names.length);
  } catch (e) { $("#src-error").textContent = e.message; }
  finally { btn.disabled = false; btn.textContent = label; }
}

// --- dashboard (главная) ----------------------------------------------------

let dashState = {};
let dashTimer = null;
let dashBusy = "";  // какой инструмент сейчас переключается (блокируем его тумблер)
let dashPending = null;  // {tool, on} — оптимистичное положение тумблера, пока крутится старт/стоп
let dashGen = 0;  // поколение опроса дашборда — чтобы устаревший in-flight loadDashboard не перетёр свежее состояние

async function loadDashboard() {
  if (dashBusy) return;  // идёт переключение — не перетирать положение тумблера
  const gen = ++dashGen;  // метка опроса: если в полёте случится toggle/новый опрос — этот устареет
  const [winws, proxy, tg, hosts] = await Promise.all([
    api("winws_state").catch(() => null),
    api("proxy_state").catch(() => null),
    api("tg_state").catch(() => null),
    api("hosts_state").catch(() => null),
  ]);
  // пока ждали ответы, юзер мог кликнуть тумблер (dashBusy) или запуститься свежий опрос —
  // тогда этот снимок уже неактуален, его данные перетёрли бы правильное состояние («пьяное» мигание)
  if (gen !== dashGen || dashBusy) return;
  dashState = { winws, proxy, tg, hosts };
  renderDashboard();
}

// карточка-инструмент: иконка + название/подпись + переключатель (или статус)
// Списки могут содержать и домены, и IP/подсети. Для готовности прокси важна их
// сумма: список из одних только IP — полностью рабочая настройка (ip_cidr в route),
// поэтому гейтить запуск на количестве доменов нельзя.
function proxyTargets(st) {
  return (st.domains || 0) + (st.ips || 0);
}

function proxyScope(st) {
  const parts = [];
  if (st.domains) parts.push(`${st.domains} доменов`);
  if (st.ips) parts.push(`${st.ips} IP`);
  return parts.join(" · ") || "0 записей";
}

function dashTool(o) {
  // пока идёт переключение — показываем тумблер в ЦЕЛЕВОМ положении (оптимистично) и
  // подпись «Включается…», не дожидаясь, пока процесс реально поднимется
  const pend = !!dashPending && dashPending.tool === o.tool;
  const on = pend ? dashPending.on : o.on;
  const disabled = pend || o.disabled;
  const meta = pend
    ? `<span class="dash-pending">${on ? "Включается" : "Выключается"}…</span>`
    : o.meta;
  const sw = o.toggle === false
    ? `<span class="dash-stat">${esc(o.statText || "")}</span>`
    : `<label class="switch dash-switch" title="${on ? "Выключить" : "Включить"}">
         <input type="checkbox" data-dash="${o.tool}" ${on ? "checked" : ""} ${disabled ? "disabled" : ""}>
         <span class="slider"></span>
       </label>`;
  return `<div class="dash-tool ${on ? "on" : ""} ${pend ? "pending" : ""} ${o.disabled ? "off-disabled" : ""}" data-go="${o.tab}">
    <div class="dash-ic">${o.icon}</div>
    <div class="dash-tool-body">
      <div class="dash-tool-name">${esc(o.name)}</div>
      <div class="dash-tool-meta">${meta}</div>
    </div>
    ${sw}
  </div>`;
}

function renderDashHero() {
  const el = $("#dash-hero");
  if (!el) return;
  const { winws, proxy, tg, hosts } = dashState;
  const tools = [winws, proxy, tg, hosts].filter(Boolean);
  // у hosts нет процесса/running — «включено» там значит applied (см. dashToggle)
  const onCount = tools.filter(t => t.running ?? t.applied).length;
  const guard = !!(winws?.running || proxy?.running || hosts?.applied);  // «защита» = обход, прокси или hosts
  el.className = "dash-hero " + (guard ? "guard" : "idle");
  el.innerHTML = `
    <div class="dash-shield">${icon("shield")}</div>
    <div class="dash-hero-text">
      <div class="dash-hero-title">${guard ? "Защита активна" : "Защита выключена"}</div>
      <div class="dash-hero-sub">
        ${onCount} из ${tools.length} включено
        <span class="dash-dot">·</span>
        ${isAdmin ? "права администратора есть" : "<span class='dash-warn'>нет прав администратора</span>"}
      </div>
    </div>
    <div class="dash-pulse"></div>`;
}

function renderDashboard() {
  renderDashHero();
  const { winws, proxy, tg, hosts } = dashState;
  const cards = [];

  if (winws) {
    const strat = winws.strategies?.find(s => s.id === winws.current)?.name;
    const hasStrat = winws.current || winwsSelected || winws.last_strategy || winws.strategies?.[0]?.id;
    cards.push(dashTool({
      tool: "winws", tab: "strategies", icon: icon("shield"), name: "DPI-обход",
      on: winws.running, disabled: dashBusy === "winws" || (!winws.running && !hasStrat),
      meta: winws.running && strat
        ? `Стратегия «${esc(strat)}»`
        : `zapret2 ${esc(winws.version || "")} · обход блокировок`,
    }));
  }
  if (proxy) {
    const mode = proxy.mode === "tun" ? "TUN" : "PAC";
    const ready = proxy.core?.present && proxy.parsed && proxyTargets(proxy) > 0;
    cards.push(dashTool({
      tool: "proxy", tab: "proxy", icon: icon("globe"), name: "Прокси",
      on: proxy.running, disabled: dashBusy === "proxy" || (!proxy.running && !ready),
      meta: proxy.running
        ? `${esc(proxy.parsed?.server || "")} · ${proxyScope(proxy)} · ${mode}`
        : (proxy.parsed ? `${proxyScope(proxy)} · режим ${mode}` : "ссылка не задана"),
    }));
  }
  if (tg) {
    cards.push(dashTool({
      tool: "tg", tab: "telegram", icon: icon("send"), name: "Telegram-прокси",
      on: tg.running, disabled: dashBusy === "tg",
      meta: tg.running ? `${esc(tg.host || "127.0.0.1")}:${esc(String(tg.port || ""))}`
                       : "ускорение Telegram",
    }));
  }
  if (hosts) {
    // привязан хотя бы один список — есть что включать (иначе тумблер мёртвый, как winws без стратегии)
    const bound = Object.values(hosts.assignments || {}).some(l => l.length);
    cards.push(dashTool({
      tool: "hosts", tab: "hosts", icon: icon("unlock"), name: "Разблокировка hosts",
      on: hosts.applied,
      disabled: dashBusy === "hosts" || (!hosts.applied && !bound),
      meta: hosts.applied
        ? `${hosts.count} записей в hosts`
        : (bound ? "привязки заданы · выключено" : "сервисы не выбраны"),
    }));
  }

  $("#dash-grid").innerHTML = cards.join("") || `<div class="empty">Нет данных.</div>`;
  renderDashFoot();
}

// компактная строка версий внизу (проверка обновлений — в Настройках)
function renderDashFoot() {
  const el = $("#dash-foot");
  if (!el) return;
  if (!sourcesState.length) { el.innerHTML = ""; return; }
  const chips = sourcesState.filter(s => s.kind !== "service").map(s =>
    `<span class="dash-chip">${esc(s.name.split("(")[0].trim())} <b>${
      esc(s.version || s.current || "—")}</b></span>`).join("");
  el.innerHTML = `<div class="dash-chips">${chips}</div>`;
}

async function dashToggle(tool) {
  if (dashBusy) return;
  const s = dashState[tool] || {};
  // у hosts нет процесса: «включено» = блок реально записан в hosts (applied)
  const target = tool === "hosts" ? !s.applied : !s.running;  // куда переключаем
  dashBusy = tool;
  dashGen++;                          // обесценить любой опрос дашборда, висящий в полёте
  dashPending = { tool, on: target }; // оптимистично двигаем тумблер сразу, до ответа бэка
  renderDashboard();
  try {
    let st;
    if (tool === "winws") {
      st = target
        ? await api("winws_start", s.current || winwsSelected || s.last_strategy || s.strategies?.[0]?.id)
        : await api("winws_stop");
    } else if (tool === "proxy") {
      st = await api(target ? "proxy_start" : "proxy_stop");
    } else if (tool === "tg") {
      st = await api(target ? "tg_start" : "tg_stop");
    } else if (tool === "hosts") {
      st = await api("hosts_set_enabled", target);  // общий выключатель: ON переприменяет привязки, OFF снимает блок
    }
    // start/stop возвращают свежий state — берём его, второй полный опрос не нужен.
    // Мёржим, а не перетираем: winws.start() не отдаёт strategies, они уже в dashState.
    if (st) dashState[tool] = { ...dashState[tool], ...st };
  } catch (e) {
    toast(e.message, true);           // не поднялось (нет прав/занят порт) — откат к факту
  } finally {
    dashPending = null;
    dashBusy = "";
    renderDashboard();
  }
}

function dashAuto(on) {
  clearInterval(dashTimer);
  dashTimer = on ? setInterval(loadDashboard, 3000) : null;
}

// --- tabs ---------------------------------------------------------------------

function switchTab(e) {
  const btn = e.target.closest(".nav-item:not(:disabled)");
  if (!btn) return;
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.id === "tab-" + btn.dataset.tab)
  );
  // автопинг и статистика крутятся только на своих вкладках
  if (btn.dataset.tab === "dashboard") { loadDashboard(); dashAuto(true); }
  else dashAuto(false);
  // на каждый вход во вкладку перечитываем её состояние из бэка (источник правды),
  // иначе тумблеры расходятся с дашбордом после переключения на другой странице
  if (btn.dataset.tab === "hosts") { loadHosts(); startHostsPing(); }
  else stopHostsPing();
  if (btn.dataset.tab === "telegram") { loadTgProxy(); startTgStats(); tgLogAuto(true); }
  else { stopTgStats(); tgLogAuto(false); }
  if (btn.dataset.tab === "proxy") { loadProxy(); proxyLogAuto(true); }  // тянем лог, пока вкладка открыта
  else proxyLogAuto(false);  // ушли с вкладки — гасим автообновление лога
  if (btn.dataset.tab === "strategies") { loadStrategies(); loadWinwsLog(); winwsLogAuto(true); }
  else winwsLogAuto(false);
  if (btn.dataset.tab === "dns") startDnsPing();
  else stopDnsPing();
  if (btn.dataset.tab === "lists") loadLists();  // обновить метки прокси/hosts (могли поменять на др. вкладке)
  closeListCtxMenu();
}

// --- proxy tab (sing-box, выборочно по доменам) -----------------------------

let proxyState = {};

async function loadProxy() {
  let st;
  try { st = await api("proxy_state"); }
  catch (e) { $("#proxy-error").textContent = e.message; return; }
  proxyState = st;
  const linkEl = $("#proxy-link");
  if (document.activeElement !== linkEl) linkEl.value = st.link || "";  // не мешаем печатать
  $("#proxy-autostart").checked = !!st.autostart;
  renderProxyLists();
  renderProxyStatus();
  loadProxyLog();
}

function renderProxyLists() {
  const box = $("#proxy-lists");
  const all = proxyState.all_lists || [];
  if (!all.length) { box.innerHTML = `<div class="empty">Списков нет — добавь во вкладке «Списки».</div>`; return; }
  const sel = new Set(proxyState.lists || []);
  box.innerHTML = all.map(n => `
    <label class="list-check">
      <input type="checkbox" value="${esc(n)}" ${sel.has(n) ? "checked" : ""}>
      <span class="lc-name">${esc(n)}</span>
    </label>`).join("");
}

function renderProxyMode() {
  const mode = proxyState.mode || "pac";
  document.querySelectorAll("#proxy-mode-seg button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
  $("#proxy-mode-hint").textContent = mode === "tun"
    ? "Весь трафик всех приложений — через VPN. Списки игнорируются, нужен админ."
    : "Через прокси только выбранные домены (браузеры), остальное напрямую. Без админа.";
  // в TUN весь трафик идёт через VPN — карточка списков не нужна, прячем целиком
  $("#proxy-lists-card").style.display = mode === "tun" ? "none" : "";
}

async function setProxyMode(mode) {
  $("#proxy-error").textContent = "";
  try { proxyState = await api("proxy_set_mode", mode); renderProxyStatus(); }
  catch (e) { $("#proxy-error").textContent = e.message; }
}

function renderProxyStatus() {
  const st = proxyState, core = st.core || {};
  const box = $("#proxy-status"), btn = $("#proxy-toggle-btn");
  renderProxyMode();
  renderProxyLists();
  const tun = (st.mode || "pac") === "tun";
  $("#proxy-error").textContent = st.error || "";
  $("#proxy-download-btn").hidden = !!core.present;
  $("#proxy-version").textContent = core.present ? `sing-box ${core.version || ""}` : "sing-box не установлен";
  $("#proxy-parsed").textContent = st.parsed
    ? `${st.parsed.protocol.toUpperCase()} · ${st.parsed.server} · ${st.parsed.security} · «${st.parsed.label}»`
    : (st.link ? "не разобрано" : "ссылка не вставлена");

  const ready = core.present && st.parsed && (tun || proxyTargets(st) > 0);
  btn.disabled = !ready && !st.running;
  btn.textContent = st.running ? "Остановить" : "Запустить";
  btn.classList.toggle("danger", st.running);
  btn.classList.toggle("primary", !st.running);

  if (st.external) {
    box.className = "hosts-status on";
    box.textContent = "✓ sing-box уже работает (запущен ранее). Нажми «Остановить», чтобы выключить.";
  } else if (st.running) {
    box.className = "hosts-status on";
    box.textContent = tun
      ? "✓ Прокси работает · весь трафик идёт через VLESS (TUN)."
      : `✓ Прокси работает · ${proxyScope(st)} идут через VLESS, остальное напрямую.`;
  } else {
    box.className = "hosts-status off";
    if (!core.present) box.textContent = "sing-box не установлен — нажми «Скачать sing-box».";
    else if (!st.link) box.textContent = "Вставь ссылку сервера.";
    else if (!st.parsed) box.textContent = "Ссылка не разобрана — проверь формат.";
    else if (!tun && !proxyTargets(st)) box.textContent = "Отметь хотя бы один список для прокси.";
    else box.textContent = "Готово к запуску.";
  }
}

async function saveProxyLink() {
  try {
    proxyState = await api("proxy_set_link", $("#proxy-link").value);
    renderProxyStatus();
    toast(proxyState.parsed ? "Ссылка сохранена" : "Ссылка очищена");
  } catch (e) { $("#proxy-error").textContent = e.message; }
}

async function onProxyListToggle(e) {
  if (!e.target.closest("input[type=checkbox]")) return;
  const names = [...document.querySelectorAll("#proxy-lists input:checked")].map(c => c.value);
  try { proxyState = await api("proxy_set_lists", names); renderProxyStatus(); }
  catch (err) { $("#proxy-error").textContent = err.message; }
}

async function proxyToggle() {
  $("#proxy-toggle-btn").disabled = true;
  $("#proxy-error").textContent = "";
  try { await api(proxyState.running ? "proxy_stop" : "proxy_start"); }
  catch (e) { $("#proxy-error").textContent = e.message; }
  await loadProxy();
}

async function downloadProxyCore() {
  const dl = $("#proxy-download-btn");
  dl.disabled = true; dl.textContent = "Качаю…";
  $("#proxy-error").textContent = "";
  try { await api("proxy_download_core"); toast("sing-box установлен"); }
  catch (e) { $("#proxy-error").textContent = e.message; }
  dl.disabled = false; dl.textContent = "Скачать sing-box";
  await loadProxy();
}

async function setProxyAutostart(v) {
  try { proxyState = await api("proxy_set_autostart", v); }
  catch (e) { toast(e.message, true); }
}

// живой стрим лога: дописываем только новые байты (r.data с серверного offset),
// скролл липнет к низу, только если пользователь уже внизу — ушёл читать вверх,
// не дёргаем; r.reset = файл пересоздан (новый запуск) → перерисовать целиком.
function applyLogChunk(el, r, emptyMsg) {
  if (!r) return;
  if (r.reset) {
    el.textContent = r.data || emptyMsg;
    el.scrollTop = el.scrollHeight;
    return;
  }
  if (!r.data) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.textContent += r.data;
  if (el.textContent.length > 200000) el.textContent = el.textContent.slice(-160000);
  if (atBottom) el.scrollTop = el.scrollHeight;
}

let proxyLogTimer = null, proxyLogOffset = 0, proxyLogBusy = false;

async function loadProxyLog() {
  if (proxyLogBusy) return;  // не наслаивать запросы, если бридж тормозит
  proxyLogBusy = true;
  try {
    const r = await api("proxy_log", proxyLogOffset);
    if (r && typeof r.offset === "number") proxyLogOffset = r.offset;
    applyLogChunk($("#proxy-log"), r, "— пусто (sing-box ещё не запускался) —");
  } catch (e) { /* молча */ } finally { proxyLogBusy = false; }
}

function proxyLogAuto(on) {
  clearInterval(proxyLogTimer);
  proxyLogTimer = on ? setInterval(loadProxyLog, 300) : null;
}

// --- init -------------------------------------------------------------------

async function init() {
  const info = await api("app_info");
  isAdmin = !!info.admin;
  const badge = $("#admin-badge");
  if (info.admin) {
    badge.textContent = `v${info.version}`;
  } else {
    badge.innerHTML = `v${esc(info.version)} · ${icon("warn")} нет прав админа`;
    badge.classList.add("warn");
  }

  $("#hosts-providers").addEventListener("click", onHostsProviderClick);
  $("#hosts-lists").addEventListener("change", onListToggle);
  document.querySelector(".sidebar").addEventListener("click", switchTab);
  $("#dns-adapter").addEventListener("change", () => { renderDnsCurrent(); markActiveProvider(); });
  $("#dns-reset-btn").addEventListener("click", onDnsReset);
  $("#dns-providers").addEventListener("click", onDnsProviderAction);
  $("#dns-add-btn").addEventListener("click", addDnsProvider);
  $("#probe-save-btn").addEventListener("click", saveProbeConfig);
  $("#hprov-add-btn").addEventListener("click", addHostsProvider);
  $("#hosts-enabled").addEventListener("change", onHostsToggle);
  $("#lists-files").addEventListener("click", onListsClick);
  $("#lists-files").addEventListener("contextmenu", onListsContext);
  $("#list-ctx-menu").addEventListener("click", onListCtxMenuClick);
  document.addEventListener("click", e => { if (!e.target.closest("#list-ctx-menu")) closeListCtxMenu(); });
  document.addEventListener("contextmenu", e => { if (!e.target.closest(".list-file")) closeListCtxMenu(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeListCtxMenu(); });
  $("#editor-text").addEventListener("input", onEditorInput);
  $("#editor-text").addEventListener("blur", flushAutosave);

  $("#chebur-one-btn").addEventListener("click", checkOneDomain);
  $("#chebur-domain").addEventListener("keydown", e => { if (e.key === "Enter") checkOneDomain(); });
  $("#chebur-list-btn").addEventListener("click", checkListBlocks);

  $("#block-one-btn").addEventListener("click", checkOneReach);
  $("#block-domain").addEventListener("keydown", e => { if (e.key === "Enter") checkOneReach(); });
  $("#block-list-btn").addEventListener("click", checkListReach);

  $("#winws-list").addEventListener("click", onWinwsSelect);
  $("#winws-lists").addEventListener("change", onWinwsListToggle);
  $("#winws-toggle-btn").addEventListener("click", winwsToggle);
  $("#game-seg").addEventListener("click", e => {
    const b = e.target.closest("button[data-mode]"); if (b) setGameFilter(b.dataset.mode);
  });
  $("#ipset-seg").addEventListener("click", e => {
    const b = e.target.closest("button[data-mode]"); if (b) setIpset(b.dataset.mode);
  });
  $("#ipset-update-btn").addEventListener("click", updateIpset);
  $("#fake-slots").addEventListener("change", e => {
    const sel = e.target.closest("select[data-fake-slot]");
    if (sel) setFake(sel.dataset.fakeSlot, sel.value);
  });
  $("#winws-autostart").addEventListener("change", e => setWinwsAutostart(e.target.checked));
  $("#list-new-btn").addEventListener("click", createList);
  $("#list-new-name").addEventListener("keydown", e => { if (e.key === "Enter") createList(); });
  $("#set-interface").addEventListener("change", e => setSetting("interface", e.target.value));
  $("#set-ui-backend").addEventListener("change", e => setSetting("ui_backend", e.target.value));
  $("#set-elevate").addEventListener("change", e => setSetting("auto_elevate", e.target.checked));
  $("#set-autostart").addEventListener("change", e => setAutostart(e.target.checked));
  $("#src-check-btn").addEventListener("click", checkSourceUpdates);
  $("#src-update-btn").addEventListener("click", updateAllSources);
  $("#src-list").addEventListener("click", onSourceAction);

  $("#tg-toggle-btn").addEventListener("click", tgToggle);
  $("#tg-open-btn").addEventListener("click", tgOpenLink);
  $("#tg-copy-btn").addEventListener("click", tgCopyLink);
  $("#tg-regen-btn").addEventListener("click", tgRegenSecret);

  $("#proxy-toggle-btn").addEventListener("click", proxyToggle);
  $("#proxy-download-btn").addEventListener("click", downloadProxyCore);
  $("#proxy-link").addEventListener("change", saveProxyLink);  // авто-сохранение по уходу с поля
  $("#proxy-lists").addEventListener("change", onProxyListToggle);
  $("#proxy-autostart").addEventListener("change", e => setProxyAutostart(e.target.checked));
  $("#proxy-mode-seg").addEventListener("click", e => {
    const b = e.target.closest("button[data-mode]"); if (b) setProxyMode(b.dataset.mode);
  });
  // переключатель инструмента (чекбокс) — отдельно от клика по карточке
  $("#dash-grid").addEventListener("change", e => {
    const inp = e.target.closest("input[data-dash]");
    if (inp) dashToggle(inp.dataset.dash);
  });
  $("#dash-grid").addEventListener("click", e => {
    if (e.target.closest(".dash-switch")) return;  // клик по тумблеру — не навигация
    const g = e.target.closest("[data-go]");
    if (g) document.querySelector(`.nav-item[data-tab="${g.dataset.go}"]`)?.click();
  });
  // текстовые поля сохраняются по уходу с поля/Enter, тумблер — сразу
  ["#tg-host", "#tg-port", "#tg-secret", "#tg-autostart"].forEach(sel =>
    $(sel).addEventListener("change", tgApply));
  ["#tg-host", "#tg-port", "#tg-secret"].forEach(sel =>
    $(sel).addEventListener("keydown", e => { if (e.key === "Enter") e.target.blur(); }));

  // внешние ссылки — в системный браузер, а не внутри встроенного Chromium
  document.addEventListener("click", e => {
    const a = e.target.closest('a[target="_blank"]');
    if (!a) return;
    e.preventDefault();
    api("open_url", a.href).catch(err => toast(err.message, true));
  });

  // пауза автопинга/статистики, когда окно свёрнуто/неактивно
  document.addEventListener("visibilitychange", () => {
    const tab = $(".nav-item.active")?.dataset.tab;
    if (document.hidden || tab !== "dashboard") dashAuto(false);
    else dashAuto(true);
    if (document.hidden || tab !== "hosts") stopHostsPing();
    else startHostsPing();
    if (document.hidden || tab !== "telegram") stopTgStats();
    else startTgStats();
    if (document.hidden || tab !== "proxy") proxyLogAuto(false);
    else proxyLogAuto(true);
    if (document.hidden || tab !== "strategies") winwsLogAuto(false);
    else winwsLogAuto(true);
    if (document.hidden || tab !== "telegram") tgLogAuto(false);
    else tgLogAuto(true);
    if (document.hidden || tab !== "dns") stopDnsPing();
    else startDnsPing();
  });

  await loadHosts();
  loadDnsState();
  loadProbeConfig();
  loadLists();
  loadBlocks();
  loadStrategies();
  loadFilters();
  loadSettings();
  loadSources();
  loadTgProxy().then(tgCheckUpdate);
  loadDashboard();      // Дашборд — вкладка по умолчанию
  dashAuto(true);
}

initBridge().then(init);
