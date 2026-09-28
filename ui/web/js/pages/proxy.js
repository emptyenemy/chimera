"use strict";
/* Прокси — sing-box по VLESS/Trojan/SS/VMess-ссылке, выборочно по доменам (PAC)
   или на весь трафик (TUN). Состояние — Store.get("proxy") (хаб, опрашивается
   всегда). Своих опросов страница не заводит — только реакция на Store. */

(() => {
  let root;
  let lastSavedLink = null;   // чтобы не слать одну и ту же ссылку дважды подряд
  const busy = new Set();     // ключи операций в полёте — спиннеры/disabled в render()

  const targets = st => (st?.domains || 0) + (st?.ips || 0);
  const scopeText = st => {
    const parts = [];
    if (st?.domains) parts.push(`${fmtNum(st.domains)} ${plural(st.domains, "домен", "домена", "доменов")}`);
    if (st?.ips) parts.push(`${fmtNum(st.ips)} IP`);
    return parts.join(" · ") || "списки не выбраны";
  };

  function render() {
    const st = Store.get("proxy");
    const admin = Store.get("app")?.admin !== false;
    morph(root.querySelector("[data-slot=status]"), statusHtml(st, admin));
    morph(root.querySelector("[data-slot=mode]"), modeHtml(st));
    morph(root.querySelector("[data-slot=link]"), linkHtml(st));
    const listsCard = root.querySelector("[data-slot=lists-card]");
    if (listsCard) listsCard.hidden = (st?.mode || "pac") === "tun";
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
    const tun = (st.mode || "pac") === "tun";
    const ready = core.present && st.parsed && (tun || targets(st) > 0);
    const on = st.running;
    const working = busy.has("toggle");
    const downloading = busy.has("download");

    let desc;
    if (st.external) desc = "sing-box уже работает — запущен раньше, вне этой сессии.";
    else if (on) desc = tun ? "Прокси работает · весь трафик идёт через VLESS (TUN)." : `Прокси работает · ${scopeText(st)} идут через VLESS, остальное напрямую.`;
    else if (!core.present) desc = "sing-box не установлен — скачай ядро.";
    else if (!st.link) desc = "Вставь ссылку сервера ниже.";
    else if (!st.parsed) desc = "Ссылка не разобрана — проверь формат.";
    else if (!tun && !targets(st)) desc = "Отметь хотя бы один список для прокси.";
    else desc = "Готово к запуску.";

    let reason = "";
    if (!ready && !on) {
      if (!core.present) reason = "Сначала скачай ядро sing-box";
      else if (!st.link) reason = "Вставь ссылку сервера";
      else if (!st.parsed) reason = "Ссылка не разобрана";
      else if (!tun) reason = "Отметь хотя бы один список";
    }

    return `
      <div class="card compact px-status${on ? " is-on" : ""}">
        <div class="card-content px-status-top">
          <div class="grow">
            <span class="badge ${on ? "success" : "outline muted"}"><span class="dot ${on ? "on" : ""}"></span>${on ? "Работает" : "Остановлено"}</span>
            <p class="px-status-desc">${esc(desc)}</p>
            ${st.error ? `<div class="alert destructive px-alert">${ic("circle-alert")}<div class="alert-desc">${esc(st.error)}</div></div>` : ""}
          </div>
          <div class="px-status-actions">
            ${!core.present ? `<button type="button" class="btn outline${downloading ? " busy" : ""}" data-download ${downloading ? "disabled" : ""}>
              ${downloading ? ic("loader-circle") : ic("download")}${downloading ? "Скачиваю…" : "Скачать sing-box"}</button>` : ""}
            <button type="button" class="btn${on ? " destructive" : ""}${working ? " busy" : ""}" data-toggle-proxy
              ${(!ready && !on) || working ? "disabled" : ""} ${reason ? `data-tip="${esc(reason)}"` : ""}>
              ${working ? ic("loader-circle") : ""}${on ? "Остановить" : "Запустить"}
            </button>
          </div>
        </div>
        <div class="card-content px-status-foot">
          <div class="switch-row px-autostart">
            <span class="muted">Автозапуск</span>
            ${switchHtml(!!st.autostart, "data-autostart")}
          </div>
          <span class="muted mono">${core.present ? `sing-box ${esc(core.version || "?")}` : "sing-box не установлен"}</span>
        </div>
      </div>
      ${tun && st.needs_admin && !admin ? `<div class="alert warning">${ic("triangle-alert")}
        <div class="alert-title">Режим TUN требует администратора</div>
        <div class="alert-desc">Переключись на «Прокси (PAC)» или перезапусти Chimera от имени администратора.</div>
      </div>` : ""}`;
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

  // --- режим PAC / TUN ---------------------------------------------------------

  function modeHtml(st) {
    if (!st) return skeletonHtml(2, 32);
    const mode = st.mode || "pac";
    return `
      <div class="between">
        <div class="tabs-list">
          <button type="button" class="tabs-trigger" data-mode="pac" aria-selected="${mode === "pac"}">${ic("filter")}Прокси (PAC)</button>
          <button type="button" class="tabs-trigger" data-mode="tun" aria-selected="${mode === "tun"}">${ic("network")}TUN</button>
        </div>
        <p class="hint px-mode-hint">${mode === "tun"
          ? "Весь трафик всех приложений — через VPN. Списки игнорируются, нужен админ."
          : "Через прокси только выбранные домены (браузеры), остальное — напрямую. Без админа."}</p>
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
      </div>
      <p class="hint px-lists-scope">${scopeText(st)} пойдут через VLESS, остальное — мимо прокси.</p>`;
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
            <p class="page-desc">Поднимает sing-box по ссылке сервера (vless / trojan / ss / vmess) — выборочно по доменам или на весь трафик.</p>
          </div>
        </div>
        <div class="stack">
          <div data-slot="status"></div>

          <div class="card compact">
            <div class="card-header"><div class="card-title">${ic("sliders-horizontal")}Режим</div></div>
            <div class="card-content" data-slot="mode"></div>
          </div>

          <div class="card">
            <div class="card-header">
              <div class="card-title">${ic("link")}Сервер</div>
              <p class="card-description">Ссылка-подписка: vless://, trojan://, ss:// или vmess://.</p>
            </div>
            <div class="card-content stack-sm">
              <textarea class="textarea mono px-link" data-link spellcheck="false"
                placeholder="vless://uuid@host:443?security=reality&amp;sni=...#Мой сервер"></textarea>
              <div data-slot="link"></div>
            </div>
          </div>

          <div class="card compact" data-slot="lists-card">
            <div class="card-header">
              <div class="card-title">${ic("network")}Какие списки гнать через прокси</div>
              <p class="card-description">Домены из отмеченных списков пойдут через VLESS, остальное — мимо прокси.</p>
            </div>
            <div class="card-content" data-slot="lists"></div>
          </div>

          <div class="card compact">
            <div class="card-header"><div class="card-title">${ic("terminal")}Логи sing-box</div></div>
            <div class="card-content"><pre class="log" data-log></pre></div>
          </div>
        </div>`;

      el.addEventListener("click", e => {
        if (e.target.closest("[data-toggle-proxy]")) return toggleProxy();
        if (e.target.closest("[data-download]")) return downloadCore();
        const sw = e.target.closest("[data-autostart]");
        if (sw) return onAutostart(sw.getAttribute("aria-checked") !== "true");
        const md = e.target.closest("[data-mode]");
        if (md) return setMode(md.dataset.mode);
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
