"use strict";
/* Hosts — разблокировка сервисов подменой IP в системном hosts-файле.

   Провайдеры бывают двух типов: dns (резолвит домены из списков через свой
   DoH/UDP на лету) и static (готовый набор host->IP из файла, домены не
   выбираются — весь список применяется целиком или не применяется вовсе).
   Модель выбора та же: провайдер слева, справа — что через него разблокировать
   (списки доменов для dns, один переключатель для static).

   Лёгкое состояние (applied/enabled/assignments/count/health/last_switch/
   background) всегда живёт в Store под ключом "hosts" — хаб опрашивает его без
   ленивости. Провайдеры и списки в хаб не входят (тяжелее и меняются реже) —
   грузятся один раз hosts_overview и кэшируются в замыкании между заходами. */

(() => {
  let root;
  let providers = [];
  let lists = [];
  let overviewLoaded = false;
  let selectedProvider = null;
  let pingResults = {};     // provider id -> {ok, ms}
  let enabledBusy = false;

  const REFRESH_DEFAULT_H = 6;    // часы — как DEFAULT_OPTIONS.refresh_interval у background.py
  const CHECK_DEFAULT_M = 15;     // минуты — как DEFAULT_OPTIONS.check_interval

  function state() { return Store.get("hosts") || {}; }

  function providerName(id) {
    return providers.find(p => p.id === id)?.name || id;
  }

  function listOwner(name, assignments) {
    for (const pid in assignments) if (Array.isArray(assignments[pid]) && assignments[pid].includes(name)) return pid;
    return null;
  }

  // метки времени бэкенда — unix-секунды (time.time())
  function agoText(key, mark) {
    if (mark == null) return null;
    const sec = Math.max(0, Math.round(Date.now() / 1000 - mark));
    return sec < 30 ? "только что" : `${fmtDuration(sec)} назад`;
  }

  // --- загрузка тяжёлых данных (не в хабе) ------------------------------------

  async function loadOverview() {
    try {
      const data = await api("hosts_overview");
      providers = data.providers;
      lists = data.lists;
      overviewLoaded = true;
      if (!selectedProvider || !providers.some(p => p.id === selectedProvider)) {
        selectedProvider = providers.find(p => p.type !== "static" || p.available !== false)?.id || null;
      }
      Store.set("hosts", data.state);
      render();
    } catch (e) {
      toast.error("Не удалось загрузить hosts", e.message);
    }
  }

  // --- общий выключатель -------------------------------------------------------

  async function onToggleEnabled() {
    if (enabledBusy) return;
    enabledBusy = true;
    const target = !state().applied;
    render();
    try {
      await optimistic("hosts", { applied: target }, () => api("hosts_set_enabled", target),
        { errorTitle: `Не удалось ${target ? "включить" : "выключить"} hosts` });
    } catch { /* тост уже показан */ }
    finally { enabledBusy = false; render(); }
  }

  // --- привязка списка к dns-провайдеру: применяется сразу -----------------------

  async function toggleListAssignment(name, checked) {
    if (!selectedProvider) return;
    const st = state();
    const mapping = {};
    for (const pid in (st.assignments || {})) {
      const v = st.assignments[pid];
      mapping[pid] = Array.isArray(v) ? [...v] : v;
    }
    for (const pid in mapping) if (Array.isArray(mapping[pid])) mapping[pid] = mapping[pid].filter(x => x !== name);
    if (checked) (mapping[selectedProvider] ||= []).push(name);
    for (const pid in mapping) if (Array.isArray(mapping[pid]) && !mapping[pid].length) delete mapping[pid];
    try {
      await optimistic("hosts", { assignments: mapping }, () => api("hosts_set_assignments", mapping),
        { errorTitle: "Не удалось применить привязку" });
    } catch { /* тост уже показан, стор откатен */ }
  }

  // static ничего не выбирает списками — привязка это просто «включён/нет» (true в assignments)
  async function toggleStaticAssignment(id, checked) {
    const st = state();
    const mapping = {};
    for (const pid in (st.assignments || {})) mapping[pid] = st.assignments[pid];
    if (checked) mapping[id] = true; else delete mapping[id];
    try {
      await optimistic("hosts", { assignments: mapping }, () => api("hosts_set_assignments", mapping),
        { errorTitle: "Не удалось применить" });
    } catch { /* тост уже показан */ }
  }

  function selectProvider(id) {
    const p = providers.find(x => x.id === id);
    if (p?.type === "static" && p.available === false) return;  // недоступный встроенный список не выбрать
    selectedProvider = id;
    render();
  }

  // --- добавление / удаление провайдера -----------------------------------------

  function openAddProvider() {
    openDialog({
      title: "Свой DNS-провайдер",
      description: "Провайдер должен уметь обходить блокировки — подставлять свой IP на заблокированный домен.",
      body: `
        <div class="stack-sm">
          <div class="field"><label class="label">Название</label>
            <input class="input" data-f="name" placeholder="Мой провайдер"></div>
          <div class="field"><label class="label">DoH-адрес</label>
            <input class="input mono" data-f="doh" placeholder="https://host/dns-query (необязательно)"></div>
          <div class="row">
            <div class="field"><label class="label">IP сервера</label>
              <input class="input mono" data-f="ip1" placeholder="необязательно"></div>
            <div class="field"><label class="label">Доп. IP</label>
              <input class="input mono" data-f="ip2" placeholder="необязательно"></div>
          </div>
        </div>`,
      footer: `<button class="btn outline" data-close>Отмена</button><button class="btn" data-ok>Добавить</button>`,
      onMount(h) {
        const val = f => h.el.querySelector(`[data-f="${f}"]`).value.trim();
        h.el.querySelector("[data-ok]").addEventListener("click", () => withBusy(h.el.querySelector("[data-ok]"), async () => {
          try {
            await api("hosts_add_provider", val("name"), val("doh"), [val("ip1"), val("ip2")]);
            toast.success("Провайдер добавлен.");
            h.close(true);
            await loadOverview();
          } catch (e) { toast.error("Не удалось добавить", e.message); }
        }));
      },
    });
  }

  async function deleteProvider(id) {
    const p = providers.find(x => x.id === id);
    const ok = await confirmDialog({
      title: "Удалить провайдера?",
      description: `Провайдер «${p?.name || id}» и его привязки будут удалены.`,
      confirmText: "Удалить", destructive: true,
    });
    if (!ok) return;
    try {
      await api("hosts_delete_provider", id);
      if (selectedProvider === id) selectedProvider = null;
      toast.success("Провайдер удалён.");
      await loadOverview();
    } catch (e) { toast.error("Не удалось удалить", e.message); }
  }

  // --- автопинг: свой цикл на тик, все провайдеры параллельно, без наложения ----

  // результат рисуется сразу по приходу: недоступный провайдер отвечает таймаутом
  // в секунды и не должен держать «…» у всех остальных
  const renderSoon = rafThrottle(() => render());

  async function pingAll() {
    // недоступный встроенный список пинговать нечего — причина уже показана в строке
    const targets = providers.filter(p => !(p.type === "static" && p.available === false));
    if (!targets.length) return;
    await Promise.allSettled(targets.map(async p => {
      try { pingResults[p.id] = await api("hosts_ping_one", p.id); }
      catch { pingResults[p.id] = { ok: false, ms: null }; }
      renderSoon();
    }));
  }

  // --- рендер --------------------------------------------------------------------

  function pingHtml(id) {
    const r = pingResults[id];
    if (!r) return `<span class="dot"></span><span class="muted">…</span>`;
    if (!r.ok) return `<span class="dot err"></span><span class="muted">нет ответа</span>`;
    if (r.ms == null) return `<span class="dot on"></span><span class="muted">доступен</span>`;
    const cls = r.ms < 80 ? "on" : r.ms < 250 ? "warn" : "err";
    return `<span class="dot ${cls}"></span><span class="num">${fmtNum(r.ms)} мс</span>`;
  }

  function adminAlertHtml() {
    if (Store.get("app")?.admin !== false) return "";
    return `<div class="alert warning" data-key="admin-alert">${ic("triangle-alert")}
      <div class="alert-title">Нет прав администратора</div>
      <div class="alert-desc">Запись в hosts потребует перезапуска программы от имени администратора.</div></div>`;
  }

  function lastSwitchHtml(st) {
    if (!st.last_switch) return "";
    const { from, to, reason } = st.last_switch;
    const ago = agoText("switch", st.last_switch.when);
    return `<div class="alert" data-key="last-switch">${ic("refresh-cw")}
      <div class="alert-title">Автопереключение провайдера</div>
      <div class="alert-desc">${esc(providerName(from))} → ${esc(providerName(to))} — ${esc(reason)}${ago ? ` · ${ago}` : ""}</div>
    </div>`;
  }

  function statusHtml() {
    const st = state();
    const pairs = Object.entries(st.assignments || {}).filter(([, v]) => (Array.isArray(v) ? v.length : v));
    if (enabledBusy) return badgeHtml("Применяю…", "outline");
    if (st.enabled === false) {
      return pairs.length ? badgeHtml("Выключено — привязки сохранены", "outline", "power")
                           : badgeHtml("Выключено", "outline", "power");
    }
    if (pairs.length && st.applied) {
      return badgeHtml(`Работает · ${fmtNum(st.count || 0)} ${plural(st.count || 0, "запись", "записи", "записей")}`,
        "success", "check");
    }
    return badgeHtml("Сервисы не выбраны", "outline", "info");
  }

  function healthLineHtml(st) {
    if (!st.health || !st.health.total) return "";
    const pct = Math.round((st.health.ratio || 0) * 100);
    const ago = agoText("health", st.health.checked_at);
    const tone = pct >= 80 ? "success" : pct >= 50 ? "warning" : "danger";
    return `<p class="hosts-health muted" data-key="health">${ic("activity")}
      <span class="badge ${tone}">${pct}% живых</span>
      <span>${fmtNum(st.health.total)} ${plural(st.health.total, "запись", "записи", "записей")} проверено${ago ? ` · ${ago}` : ""}</span>
    </p>`;
  }

  function toggleCardHtml() {
    const st = state();
    return `
      <div class="card compact" data-key="card-toggle">
        <div class="card-header">
          <div class="card-title">${ic("unlock")}Разблокировка hosts</div>
          <div class="card-description">Подменяет IP выбранных сервисов через DNS-провайдера — работает без смены системного DNS.</div>
          <div class="card-action">${switchHtml(!!st.applied, "data-toggle-enabled", { disabled: enabledBusy, pending: enabledBusy })}</div>
        </div>
        <div class="card-content stack-sm">
          ${statusHtml()}
          ${healthLineHtml(st)}
        </div>
      </div>`;
  }

  function providerHealthBadge(st, id) {
    const h = st.health?.providers?.[id];
    if (!h || !h.total) return "";
    const pct = Math.round((h.ratio || 0) * 100);
    return badgeHtml(`${pct}%`, pct >= 80 ? "success" : pct >= 50 ? "warning" : "danger");
  }

  function providerRowHtml(p, st) {
    const isStatic = p.type === "static";
    const unavailable = isStatic && p.available === false;
    const on = isStatic ? !!st.assignments?.[p.id] : (st.assignments?.[p.id] || []).length;
    const canDelete = !isStatic && !p.builtin;
    const desc = unavailable ? p.reason
      : isStatic ? "Встроенный список — записи применяются целиком"
      : (p.servers?.length ? esc(p.servers.join(" · ")) : (p.doh ? esc(p.doh) : "—"));
    return `
      <div class="item ${unavailable ? "" : "interactive"} hosts-prov${unavailable ? " is-unavailable" : ""}"
           data-key="prov-${esc(p.id)}" data-id="${esc(p.id)}"
           role="radio" tabindex="${unavailable ? -1 : 0}" aria-disabled="${unavailable}"
           ${p.id === selectedProvider ? 'aria-selected="true"' : ""}
           ${unavailable ? `data-tip="${esc(p.reason || "")}"` : ""}>
        <div class="item-media">${ic(isStatic ? "package" : (p.doh ? "lock" : "server"))}</div>
        <div class="item-body">
          <div class="hosts-prov-name">${esc(p.name)}${on ? badgeHtml(isStatic ? "включён" : String(on), "secondary") : ""}${providerHealthBadge(st, p.id)}</div>
          <div class="item-desc">${unavailable ? esc(desc) : desc}</div>
        </div>
        <div class="hosts-ping">${unavailable ? `<span class="muted">—</span>` : pingHtml(p.id)}</div>
        ${canDelete ? `<button class="btn ghost xs icon-btn" data-del="${esc(p.id)}" data-tip="Удалить">${ic("trash-2")}</button>` : ""}
      </div>`;
  }

  function providersHtml() {
    if (!overviewLoaded) return skeletonHtml(3, 56);
    if (!providers.length) {
      return emptyHtml({ icon: "server", title: "Нет обходных провайдеров", desc: "Добавь своего ниже." });
    }
    const st = state();
    return `<div class="item-list" data-key="prov-list">${providers.map(p => providerRowHtml(p, st)).join("")}</div>`;
  }

  function listsHtml() {
    if (!overviewLoaded) return skeletonHtml(4, 32);
    if (!lists.length) {
      return emptyHtml({ icon: "list-checks", title: "Списков нет", desc: "Добавь домены на странице «Списки»." });
    }
    const assignments = state().assignments || {};
    return `<div class="stack-sm" data-key="lists-list">${lists.map(l => {
      const owner = listOwner(l.name, assignments);
      const mine = owner === selectedProvider;
      const elsewhere = owner && !mine;
      return `
      <label class="check-row hosts-list-row${elsewhere ? " is-taken" : ""}" data-key="list-${esc(l.name)}">
        <input type="checkbox" class="checkbox" value="${esc(l.name)}" ${mine ? "checked" : ""} ${!selectedProvider || elsewhere ? "disabled" : ""}>
        <span class="grow">${esc(l.name)}</span>
        ${elsewhere ? `<span class="muted hosts-owner">→ ${esc(providerName(owner))}</span>` : `<span class="muted num">${fmtNum(l.count)}</span>`}
      </label>`;
    }).join("")}</div>`;
  }

  // правая карточка зависит от типа выбранного провайдера: у dns — списки
  // доменов, у static — просто переключатель (записи применяются целиком)
  function rightCardHtml() {
    const p = providers.find(x => x.id === selectedProvider);
    if (p?.type === "static") {
      const on = !!state().assignments?.[p.id];
      return `
        <div class="card compact" data-key="card-lists">
          <div class="card-header">
            <div class="card-title">${ic("package")}Встроенный список</div>
            <div class="card-description">«${esc(p.name)}» — фиксированный набор адресов, домены отдельно не выбираются.</div>
          </div>
          <div class="card-content">
            <div class="switch-row hosts-static-row">
              <span>Применять записи «${esc(p.name)}»</span>
              ${switchHtml(on, `data-static-toggle="${esc(p.id)}"`)}
            </div>
          </div>
        </div>`;
    }
    return `
      <div class="card compact" data-key="card-lists">
        <div class="card-header">
          <div class="card-title">${ic("list-checks")}Что разблокировать</div>
          <div class="card-description">${selectedProvider ? `Списки для «${esc(providerName(selectedProvider))}»` : "Выбери провайдера слева"}</div>
        </div>
        <div class="card-content">${listsHtml()}</div>
      </div>`;
  }

  // --- «Автоматика»: автообновление / чекер / автопереключение -------------------

  function parseIntervalInput(value, unitSeconds, defaultUnits) {
    value = String(value ?? "").trim();
    if (!value) return defaultUnits * unitSeconds;
    const n = parseInt(value, 10);
    if (!Number.isFinite(n) || n <= 0) return defaultUnits * unitSeconds;
    return n * unitSeconds;
  }

  // порядок из настроек может отставать от списка dns-провайдеров (добавили
  // нового, удалили старого) — довешиваем недостающих в конец, забытых убираем
  function effectiveOrder(bg, dnsProviders) {
    const known = new Set(dnsProviders.map(p => p.id));
    const order = (bg.provider_order || []).filter(id => known.has(id));
    for (const p of dnsProviders) if (!order.includes(p.id)) order.push(p.id);
    return order;
  }

  // hosts_set_background() отдаёт целиком объект background (не обёрнутый) —
  // optimistic() мержит результат команды прямо в ключ хаба, а нам нужно на
  // уровень глубже (hosts.background), поэтому applyResult:false и патчим сами.
  function saveBackground(patch) {
    const bg = { ...(state().background || {}), ...patch };
    return optimistic("hosts", { background: bg }, () => api("hosts_set_background", patch),
      { applyResult: false, errorTitle: "Автоматика: не удалось сохранить" }).catch(() => {});
  }

  function onBgSwitch(key, value) { saveBackground({ [key]: value }); }

  function onBgNum(field, value) {
    if (field === "refresh_interval_h") saveBackground({ refresh_interval: parseIntervalInput(value, 3600, REFRESH_DEFAULT_H) });
    else saveBackground({ check_interval: parseIntervalInput(value, 60, CHECK_DEFAULT_M) });
  }

  function moveOrder(id, dir) {
    const bg = state().background || {};
    const order = effectiveOrder(bg, providers.filter(p => p.type === "dns"));
    const i = order.indexOf(id), j = i + dir;
    if (i < 0 || j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    saveBackground({ provider_order: order });
  }

  function orderHtml(order) {
    if (!order.length) return `<p class="hint">Нет dns-провайдеров для приоритета переключения.</p>`;
    return `<div class="stack-sm hosts-order" data-key="order">${order.map((id, i) => `
      <div class="item hosts-order-row" data-key="ord-${esc(id)}">
        <span class="muted hosts-order-num">${i + 1}</span>
        <span class="grow">${esc(providerName(id))}</span>
        <button type="button" class="btn ghost xs icon-btn" data-order-up="${esc(id)}" ${i === 0 ? "disabled" : ""} data-tip="Выше">${ic("chevron-up")}</button>
        <button type="button" class="btn ghost xs icon-btn" data-order-down="${esc(id)}" ${i === order.length - 1 ? "disabled" : ""} data-tip="Ниже">${ic("chevron-down")}</button>
      </div>`).join("")}</div>`;
  }

  function backgroundHtml() {
    if (!overviewLoaded) return skeletonHtml(4, 32);
    const bg = state().background || {};
    const refreshH = bg.refresh_interval ? Math.round(bg.refresh_interval / 3600) : "";
    const checkM = bg.check_interval ? Math.round(bg.check_interval / 60) : "";
    const order = effectiveOrder(bg, providers.filter(p => p.type === "dns"));
    return `
      <div class="stack-sm">
        <div class="switch-row">
          <div><div class="label">Автообновление IP</div><p class="hint">Пересчитывает адреса dns-привязок по расписанию — провайдер мог сменить IP.</p></div>
          ${switchHtml(bg.refresh_enabled !== false, `data-bg-switch="refresh_enabled"`)}
        </div>
        <div class="field hosts-bg-num">
          <label class="label muted">Интервал обновления, часов</label>
          <input class="input sm mono" type="text" inputmode="numeric" data-bg-num="refresh_interval_h" placeholder="${REFRESH_DEFAULT_H}" value="${esc(refreshH)}">
        </div>
      </div>
      <div class="separator"></div>
      <div class="stack-sm">
        <div class="switch-row">
          <div><div class="label">Проверка живых записей</div><p class="hint">TCP+TLS-чекер уже применённых записей — считает долю живых (health).</p></div>
          ${switchHtml(bg.check_enabled !== false, `data-bg-switch="check_enabled"`)}
        </div>
        <div class="field hosts-bg-num">
          <label class="label muted">Интервал проверки, минут</label>
          <input class="input sm mono" type="text" inputmode="numeric" data-bg-num="check_interval_m" placeholder="${CHECK_DEFAULT_M}" value="${esc(checkM)}">
        </div>
      </div>
      <div class="separator"></div>
      <div class="stack-sm">
        <div class="switch-row">
          <div><div class="label">Автопереключение</div><p class="hint">Привязка деградировала (мало живых записей) — переключить на следующего живого dns-провайдера по порядку ниже.</p></div>
          ${switchHtml(!!bg.autoswitch_enabled, `data-bg-switch="autoswitch_enabled"`)}
        </div>
        ${orderHtml(order)}
      </div>`;
  }

  function render() {
    const st = state();
    morph(root.querySelector("[data-slot=body]"), `
      ${adminAlertHtml()}
      ${lastSwitchHtml(st)}
      ${toggleCardHtml()}
      <div class="grid-2">
        <div class="card compact" data-key="card-providers">
          <div class="card-header">
            <div class="card-title">${ic("globe")}DNS-провайдер</div>
            <div class="card-description">Кому резолвить выбранные сервисы</div>
            <div class="card-action"><button class="btn ghost sm" data-add-provider>${ic("plus")}Добавить</button></div>
          </div>
          <div class="card-content">${providersHtml()}</div>
        </div>
        ${rightCardHtml()}
      </div>
      <div class="card compact" data-key="card-background">
        <div class="card-header">
          <div class="card-title">${ic("sliders-horizontal")}Автоматика</div>
          <div class="card-description">Фоновое обновление, проверка живых записей и автопереключение — модуль работает и без открытого окна.</div>
        </div>
        <div class="card-content">${backgroundHtml()}</div>
      </div>`);
  }

  Pages.define({
    id: "hosts", title: "Hosts", icon: "server", group: "Сеть",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Hosts</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;

      el.addEventListener("click", e => {
        if (e.target.closest("[data-toggle-enabled]")) return onToggleEnabled();
        if (e.target.closest("[data-add-provider]")) return openAddProvider();
        const del = e.target.closest("[data-del]");
        if (del) return deleteProvider(del.dataset.del);
        const row = e.target.closest(".hosts-prov");
        if (row) return selectProvider(row.dataset.id);
        const st = e.target.closest("[data-static-toggle]");
        if (st) return toggleStaticAssignment(st.dataset.staticToggle, st.getAttribute("aria-checked") !== "true");
        const bs = e.target.closest("[data-bg-switch]");
        if (bs) return onBgSwitch(bs.dataset.bgSwitch, bs.getAttribute("aria-checked") !== "true");
        const up = e.target.closest("[data-order-up]");
        if (up) return moveOrder(up.dataset.orderUp, -1);
        const down = e.target.closest("[data-order-down]");
        if (down) return moveOrder(down.dataset.orderDown, 1);
      });
      el.addEventListener("change", e => {
        const cb = e.target.closest(".hosts-list-row input[type=checkbox]");
        if (cb) return toggleListAssignment(cb.value, cb.checked);
        const num = e.target.closest("[data-bg-num]");
        if (num) return onBgNum(num.dataset.bgNum, num.value);
      });
      // Enter в числовом поле — как blur (сохранит и снимет фокус)
      el.addEventListener("keydown", e => {
        if (e.key === "Enter" && e.target.matches("[data-bg-num]")) e.target.blur();
      });

      loadOverview();
    },
    show(ctx) {
      ctx.on(["hosts", "app"], render);
      render();
      ctx.every(2500, pingAll);
    },
  });
})();
