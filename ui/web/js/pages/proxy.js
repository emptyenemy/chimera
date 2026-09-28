"use strict";
/* Прокси — sing-box по VLESS/Trojan/SS/VMess-ссылке в трёх режимах: системный
   прокси (PAC) по спискам доменов, выборочный TUN (выбранные приложения + списки)
   и полный TUN. Состояние — Store.get("proxy") (хаб, опрашивается всегда). Своих
   опросов страница не заводит — только реакция на Store. */

(() => {
  let root;
  let lastSavedLink = null;   // чтобы не слать одну и ту же ссылку дважды подряд
  const busy = new Set();     // ключи операций в полёте — спиннеры/disabled в render()

  const modeOf = st => st?.mode || "pac";
  const targets = st => (st?.domains || 0) + (st?.ips || 0);

  function render() {
    const st = Store.get("proxy");
    const admin = Store.get("app")?.admin !== false;
    const mode = modeOf(st);
    morph(root.querySelector("[data-slot=status]"), statusHtml(st, admin));
    morph(root.querySelector("[data-slot=mode]"), modeHtml(st));
    morph(root.querySelector("[data-slot=link]"), linkHtml(st));
    const appsCard = root.querySelector("[data-slot=apps-card]");
    if (appsCard) appsCard.hidden = mode !== "split";
    morph(root.querySelector("[data-slot=apps]"), appsHtml(st));
    const listsCard = root.querySelector("[data-slot=lists-card]");
    if (listsCard) listsCard.hidden = mode === "tun";
    morph(root.querySelector("[data-slot=lists]"), listsHtml(st));
    const linkEl = root.querySelector("[data-link]");
    if (linkEl && document.activeElement !== linkEl && linkEl.value !== (st?.link || "")) {
      linkEl.value = st?.link || "";
      lastSavedLink = st?.link || "";
    }
  }

  async function runBusy(key, fn) {
    busy.add(key); render();
    try { return await fn(); }
    finally { busy.delete(key); render(); }
  }

  // --- статус / пуск-стоп -------------------------------------------------------

  function statusHtml(st, admin) {
    if (!st) return `<div class="card compact"><div class="card-content">${skeletonHtml(3, 24)}</div></div>`;
    const core = st.core || {};
    const mode = modeOf(st);
    const full = mode === "tun";
    const split = mode === "split";
    const hasScope = full || targets(st) > 0 || (split && (st.apps || []).length > 0);
    const ready = core.present && st.parsed && hasScope;
    const on = st.running;
    const working = busy.has("toggle");
    const downloading = busy.has("download");

    // почему не запустить — первое, что мешает; показывается прямо в строке статуса
    let reason = "";
    if (!on) {
      if (!core.present) reason = "Нужно скачать ядро sing-box";
      else if (!st.link) reason = "Вставь ссылку сервера";
      else if (!st.parsed) reason = "Ссылка не разобрана — проверь формат";
      else if (!hasScope) reason = split ? "Выбери приложение или список" : "Отметь хотя бы один список";
      else if (st.needs_admin && !admin) reason = "Этот режим требует прав администратора";
    }

    const title = st.external ? "Работает (запущен вне Chimera)"
      : on ? `Работает · ${esc(st.parsed?.server || "")}`
      : reason ? `<span class="px-reason">${esc(reason)}</span>` : "Остановлено";

    return `
      <div class="card compact px-status${on ? " is-on" : ""}">
        <div class="card-content px-status-row">
          <span class="dot ${on ? "on" : ""}"></span>
          <div class="grow px-status-title">${title}</div>
          <label class="px-autostart"><span class="muted">Автозапуск</span>${switchHtml(!!st.autostart, "data-autostart")}</label>
          ${!core.present ? `<button type="button" class="btn sm outline${downloading ? " busy" : ""}" data-download ${downloading ? "disabled" : ""}>
            ${downloading ? ic("loader-circle") : ic("download")}${downloading ? "Скачиваю…" : "Скачать ядро"}</button>` : ""}
          <button type="button" class="btn sm${on ? " destructive" : ""}${working ? " busy" : ""}" data-toggle-proxy
            ${(!ready && !on) || (reason && !on) || working ? "disabled" : ""}>
            ${working ? ic("loader-circle") : ""}${on ? "Остановить" : "Запустить"}
          </button>
        </div>
        ${st.error ? `<div class="card-content"><div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(st.error)}</div></div></div>` : ""}
      </div>`;
  }

  async function toggleProxy() {
    if (busy.has("toggle")) return;
    const st = Store.get("proxy");
    if (!st) return;
    await runBusy("toggle", async () => {
      try {
        if (st.running) {
          await optimistic("proxy", { running: false }, () => api("proxy_stop"), { errorTitle: "Не удалось остановить прокси" });
          toast.success("Прокси остановлен.");
        } else {
          await optimistic("proxy", { running: true }, () => api("proxy_start"), { errorTitle: "Не удалось запустить прокси" });
          toast.success("Прокси запущен.");
        }
      } catch { /* тост уже показан */ }
    });
  }

  async function downloadCore() {
    if (busy.has("download")) return;
    await runBusy("download", async () => {
      try {
        const r = await api("proxy_download_core");
        if (r?.restart_required) toast.warning("sing-box обновлён", r.message);
        else toast.success("sing-box установлен", r?.version ? `версия ${r.version}` : "");
      } catch (e) { toast.error("Не удалось скачать sing-box", e.message); }
    });
  }

  function onAutostart(v) {
    optimistic("proxy", { autostart: v }, () => api("proxy_set_autostart", v),
      { errorTitle: "Автозапуск: не получилось изменить" }).catch(() => {});
  }

  // --- режим: системный прокси / выборочный TUN / полный TUN -------------------

  // одна строка на режим: чем отличается от соседних — и всё
  const MODES = [
    { id: "pac", icon: "filter", label: "Системный прокси",
      hint: "Отмеченные сайты — для браузеров и программ, которые понимают системный прокси." },
    { id: "split", icon: "git-branch", label: "Выборочно",
      hint: "Выбранные приложения и сайты — для всех программ. Игры и остальное идут напрямую." },
    { id: "tun", icon: "network", label: "Весь трафик",
      hint: "Всё через прокси, как VPN. Напрямую — только локальная сеть." },
  ];

  function modeHtml(st) {
    if (!st) return skeletonHtml(2, 32);
    const mode = modeOf(st);
    const cur = MODES.find(m => m.id === mode) || MODES[0];
    return `
      <div class="stack-sm">
        <div class="tabs-list px-modes">
          ${MODES.map(m => `<button type="button" class="tabs-trigger" data-mode="${m.id}" aria-selected="${m.id === cur.id}">${ic(m.icon)}${esc(m.label)}</button>`).join("")}
        </div>
        <p class="hint" data-key="mode-hint">${esc(cur.hint)}</p>
      </div>`;
  }

  function setMode(mode) {
    optimistic("proxy", { mode }, () => api("proxy_set_mode", mode), { errorTitle: "Режим: не удалось изменить" }).catch(() => {});
  }

  // --- ссылка сервера -----------------------------------------------------------

  // ссылку не проводим через optimistic(): она валидируется на бэкенде, а
  // toast.error() на каждую паузу посреди набора был бы навязчив — вместо тоста
  // тихая надпись под полем, как у остальных форм этой страницы.
  let linkError = null;

  function linkHtml(st) {
    if (!st) return "";
    if (linkError) return `<div class="alert destructive px-alert" data-key="parsed">${ic("circle-alert")}<div class="alert-desc">${esc(linkError)}</div></div>`;
    if (st.parsed) {
      return `<div class="cluster px-parsed" data-key="parsed">
        ${badgeHtml(st.parsed.protocol.toUpperCase(), "secondary")}
        ${badgeHtml(st.parsed.transport === "tcp" ? "TCP" : st.parsed.transport.toUpperCase(), "outline")}
        ${badgeHtml(st.parsed.server, "outline")}
        ${badgeHtml(st.parsed.security === "none" ? "без TLS" : st.parsed.security, "outline")}
        <span class="muted">«${esc(st.parsed.label)}»</span>
      </div>`;
    }
    return `<p class="hint" data-key="parsed">${st.link ? "Ссылка не разобрана — проверь формат." : "Вставь ссылку сервера: vless://, trojan://, ss:// или vmess://."}</p>`;
  }

  async function saveLink(value) {
    value = (value ?? "").trim();
    if (value === lastSavedLink) return;
    lastSavedLink = value;
    const before = Store.get("proxy");
    Store.patch("proxy", { link: value });
    try {
      const res = await api("proxy_set_link", value);
      linkError = null;
      Store.patch("proxy", res);
      toast.success(value ? "Ссылка сохранена." : "Ссылка очищена.");
    } catch (e) {
      linkError = e.message;
      Store.set("proxy", before);
      lastSavedLink = before?.link ?? "";
    } finally {
      render();
      api("hub_refresh", ["proxy"]).catch(() => {});
    }
  }

  // --- приложения для выборочного TUN -------------------------------------------
  // Выбор — только из запущенных программ: имя процесса берётся из системы как
  // есть, без угадывания. Выбранные, но сейчас не запущенные остаются в списке.

  function appsHtml(st) {
    if (!st) return skeletonHtml(2, 32);
    const apps = st.apps || [];
    const picking = busy.has("apps-pick");
    const addBtn = `<button type="button" class="btn outline sm${picking ? " busy" : ""}" data-apps-add ${picking ? "disabled" : ""}>
      ${picking ? ic("loader-circle") : ic("plus")}Добавить из запущенных</button>`;
    const list = apps.length
      ? `<div class="px-apps" data-key="apps">
          ${apps.map(a => `<span class="badge outline px-app" data-key="a-${esc(a)}">
            <span class="mono">${esc(a)}</span>
            <button type="button" class="px-app-x" data-app-remove="${esc(a)}" aria-label="Убрать ${esc(a)}" data-tip="Убрать">${ic("x")}</button>
          </span>`).join("")}
        </div>`
      : "";
    return `
      <div class="stack-sm">
        ${list}
        <div class="cluster" data-key="apps-actions">${addBtn}</div>
        <p class="hint" data-key="apps-webview">WhatsApp, Teams и другие программы на WebView2 ловятся по списку сайтов, а не по процессу.</p>
      </div>`;
  }

  function saveApps(names) {
    return optimistic("proxy", { apps: names }, () => api("proxy_set_apps", names),
      { errorTitle: "Приложения: не удалось сохранить" }).catch(() => {});
  }

  function removeApp(name) {
    const apps = (Store.get("proxy")?.apps || []).filter(a => a !== name);
    saveApps(apps);
  }

  async function pickApps() {
    if (busy.has("apps-pick")) return;
    let running;
    await runBusy("apps-pick", async () => {
      try { running = await api("proxy_apps_snapshot"); }
      catch (e) { toast.error("Не удалось получить список программ", e.message); }
    });
    if (!running) return;

    const selected = Store.get("proxy")?.apps || [];
    const chosen = new Set(selected.map(a => a.toLowerCase()));
    const runningKeys = new Set(running.map(r => r.name.toLowerCase()));
    let query = "";

    const rowsHtml = () => {
      const q = query.trim().toLowerCase();
      const items = running.filter(r => !q || r.name.toLowerCase().includes(q));
      if (!items.length) return emptyHtml({ icon: "search", title: "Ничего не нашлось", desc: q ? `Среди запущенных нет «${query.trim()}».` : "Запущенных программ не видно." });
      return items.map(r => `
        <label class="check-row px-pick-row">
          <input type="checkbox" class="checkbox" value="${esc(r.name)}" ${chosen.has(r.name.toLowerCase()) ? "checked" : ""}>
          <span class="mono grow">${esc(r.name)}</span>
          ${r.count > 1 ? `<span class="muted">×${fmtNum(r.count)}</span>` : ""}
        </label>`).join("");
    };

    openDialog({
      title: "Приложения через прокси",
      description: "Отметь запущенные программы — весь их трафик пойдёт через прокси. Программу, которой нет в списке, сначала запусти.",
      wide: true,
      body: `<div class="stack-sm">
          <div class="input-group">${ic("search")}<input class="input" data-pick-search placeholder="Поиск по имени процесса…"></div>
          <div class="px-pick-list" data-pick-list>${rowsHtml()}</div>
        </div>`,
      footer: `<button class="btn outline" data-close>Отмена</button><button class="btn" data-ok>Сохранить</button>`,
      onMount: h => {
        const listEl = h.el.querySelector("[data-pick-list]");
        const draw = () => { listEl.innerHTML = rowsHtml(); if (window.icons) window.icons(listEl); };
        h.el.querySelector("[data-pick-search]").addEventListener("input", e => { query = e.target.value; draw(); });
        listEl.addEventListener("change", e => {
          const key = e.target.value?.toLowerCase();
          if (!key) return;
          if (e.target.checked) chosen.add(key); else chosen.delete(key);
        });
        h.el.querySelector("[data-ok]").addEventListener("click", () => {
          // выбранные раньше и сейчас не запущенные — как были; среди запущенных — по галочкам
          const keep = selected.filter(a => !runningKeys.has(a.toLowerCase()));
          const picked = running.filter(r => chosen.has(r.name.toLowerCase())).map(r => r.name);
          saveApps([...keep, ...picked]);
          h.close(true);
        });
      },
    });
  }

  // --- списки для маршрутизации через прокси -----------------------------------

  function listsHtml(st) {
    if (!st) return skeletonHtml(3, 32);
    const all = st.all_lists || [];
    if (!all.length) return emptyHtml({
      icon: "list", title: "Списков нет",
      desc: "Добавь домены на странице «Списки», потом отметь нужные здесь.",
      action: `<button type="button" class="btn outline sm" data-go="lists">Перейти к спискам${ic("arrow-right")}</button>`,
    });
    const sel = new Set(st.lists || []);
    return `
      <div class="px-lists-grid" data-key="grid">
        ${all.map(n => `
          <label class="check-row" data-key="l-${esc(n)}">
            <input type="checkbox" class="checkbox" value="${esc(n)}" ${sel.has(n) ? "checked" : ""}>
            <span>${esc(n)}</span>
          </label>`).join("")}
      </div>`;
  }

  function onListsToggle() {
    const names = $$(".px-lists-grid input:checked", root).map(c => c.value);
    optimistic("proxy", { lists: names }, () => api("proxy_set_lists", names),
      { errorTitle: "Списки: не удалось сохранить" }).catch(() => {});
  }

  // --- монтаж -----------------------------------------------------------------

  let log, linkTimer = 0;

  Pages.define({
    id: "proxy", title: "Прокси", icon: "globe", group: "Обход",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Прокси</h1>
          </div>
        </div>
        <div class="stack">
          <div data-slot="status"></div>

          <div class="card compact">
            <div class="card-header"><div class="card-title">${ic("sliders-horizontal")}Режим</div></div>
            <div class="card-content" data-slot="mode"></div>
          </div>

          <div class="card compact">
            <div class="card-header"><div class="card-title">${ic("link")}Сервер</div></div>
            <div class="card-content stack-sm">
              <textarea class="textarea mono px-link" data-link spellcheck="false"
                placeholder="vless://uuid@host:443?security=reality&amp;sni=...#Мой сервер"></textarea>
              <div data-slot="link"></div>
            </div>
          </div>

          <div class="card compact" data-slot="apps-card" hidden>
            <div class="card-header"><div class="card-title">${ic("cpu")}Приложения</div></div>
            <div class="card-content" data-slot="apps"></div>
          </div>

          <div class="card compact" data-slot="lists-card">
            <div class="card-header"><div class="card-title">${ic("list")}Списки сайтов</div></div>
            <div class="card-content" data-slot="lists"></div>
          </div>

          ${foldHtml("terminal", "Логи", '<pre class="log" data-log></pre>')}
        </div>`;

      el.addEventListener("click", e => {
        if (e.target.closest("[data-toggle-proxy]")) return toggleProxy();
        if (e.target.closest("[data-download]")) return downloadCore();
        const sw = e.target.closest("[data-autostart]");
        if (sw) return onAutostart(sw.getAttribute("aria-checked") !== "true");
        const md = e.target.closest("[data-mode]");
        if (md) return setMode(md.dataset.mode);
        if (e.target.closest("[data-apps-add]")) return pickApps();
        const rm = e.target.closest("[data-app-remove]");
        if (rm) return removeApp(rm.dataset.appRemove);
        const go = e.target.closest("[data-go]");
        if (go) return Pages.go(go.dataset.go);
      });
      el.addEventListener("change", e => {
        if (e.target.closest(".px-lists-grid")) return onListsToggle();
      });
      const linkEl = el.querySelector("[data-link]");
      linkEl.addEventListener("input", () => {
        clearTimeout(linkTimer);
        linkTimer = setTimeout(() => saveLink(linkEl.value), 500);
      });
      linkEl.addEventListener("change", () => { clearTimeout(linkTimer); saveLink(linkEl.value); });

      log = new LogView(el.querySelector("[data-log]"), "proxy_log");
    },
    show(ctx) {
      ctx.on(["proxy", "app"], render);
      log.attach(ctx);
      render();
    },
  });
})();
