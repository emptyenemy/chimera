"use strict";
/* Обзор: общий статус защиты и быстрые тумблеры всех модулей.
   Эталон устройства страницы: рендер только из Store, morph() на каждое
   изменение, тумблеры — optimistic(), своих опросов нет. */

(() => {
  let root;
  let versions = null;       // локальные версии компонентов — один раз за сессию

  // Списки бывают и из доменов, и из IP/подсетей: для готовности прокси важна сумма.
  const proxyTargets = st => (st?.domains || 0) + (st?.ips || 0);
  function proxyScope(st) {
    if (st?.mode === "tun") return "весь трафик";
    const parts = [];
    const apps = st?.mode === "split" ? (st.apps || []).length : 0;
    if (apps) parts.push(`${fmtNum(apps)} ${plural(apps, "приложение", "приложения", "приложений")}`);
    if (st?.domains) parts.push(`${fmtNum(st.domains)} ${plural(st.domains, "домен", "домена", "доменов")}`);
    if (st?.ips) parts.push(`${fmtNum(st.ips)} IP`);
    return parts.join(" · ") || "списки не выбраны";
  }

  // Описание модулей: откуда брать состояние, как включать/выключать, когда тумблер мёртвый.
  const MODULES = [
    {
      key: "winws", page: "strategies", icon: "shield-check", title: "Обход DPI",
      on: st => !!st?.running,
      strategy: st => st?.current || st?.last_strategy || st?.strategies?.[0]?.id,
      blocked(st) {
        if (!st) return "Загрузка…";
        if (!st.running && !this.strategy(st)) return "Нет стратегий";
        if (!st.running && Store.get("app")?.admin === false) return "Нужны права администратора";
        return "";
      },
      meta(st) {
        if (!st) return "";
        const name = st.strategies?.find(s => s.id === (st.current || st.last_strategy))?.name;
        return st.running
          ? `Стратегия «${esc(name || st.current || "?")}»`
          : (name ? `Последняя: «${esc(name)}»` : "zapret2 · winws2");
      },
      foot: st => st?.version ? `zapret2 ${esc(st.version)}` : "",
      toggle(st, on) {
        return on ? api("winws_start", this.strategy(st)) : api("winws_stop");
      },
    },
    {
      key: "proxy", page: "proxy", icon: "globe", title: "Прокси",
      on: st => !!st?.running,
      blocked(st) {
        if (!st) return "Загрузка…";
        if (st.running) return "";
        if (!st.core?.present) return "Не скачано ядро sing-box";
        if (!st.parsed) return "Не задана ссылка";
        if (st.mode === "split" && !proxyTargets(st) && !(st.apps || []).length) return "Не выбраны приложения и списки";
        if ((st.mode || "pac") === "pac" && !proxyTargets(st)) return "Не выбраны списки";
        return "";
      },
      meta(st) {
        if (!st) return "";
        const mode = { tun: "TUN", split: "TUN выборочно" }[st.mode] || "PAC";
        if (st.running) return `${esc(st.parsed?.server || "")} · ${mode}`;
        return st.parsed ? `${esc(st.parsed.server || "")} · режим ${mode}` : "sing-box · VLESS / Trojan / SS";
      },
      foot: st => st ? proxyScope(st) : "",
      toggle: (st, on) => api(on ? "proxy_start" : "proxy_stop"),
    },
    {
      key: "tg", page: "telegram", icon: "send", title: "Telegram-прокси",
      on: st => !!st?.running,
      blocked: st => st ? "" : "Загрузка…",
      meta: st => !st ? "" : st.running
        ? `${esc(st.host || "127.0.0.1")}:${esc(st.port ?? "")}`
        : "MTProto через WebSocket",
      foot: st => st?.version ? `tg-ws-proxy ${esc(st.version)}` : "",
      toggle: (st, on) => api(on ? "tg_start" : "tg_stop"),
    },
    {
      key: "hosts", page: "hosts", icon: "unlock", title: "Разблокировка hosts",
      on: st => !!st?.applied,
      blocked(st) {
        if (!st) return "Загрузка…";
        const bound = Object.values(st.assignments || {}).some(l => l?.length);
        if (!st.applied && !bound) return "Сервисы не выбраны";
        return "";
      },
      meta: st => !st ? "" : st.applied
        ? `${fmtNum(st.count || 0)} ${plural(st.count || 0, "запись", "записи", "записей")} в hosts`
        : "Подмена IP через DNS-провайдеров",
      foot: () => "",
      toggle: (st, on) => api("hosts_set_enabled", on),
      // у hosts «включено» — это applied, а не running
      patch: on => ({ applied: on }),
    },
  ];

  function heroHtml() {
    const guard = Status.guard();
    const n = Status.count();
    const admin = Store.get("app")?.admin !== false;
    return `
      <div class="card dash-hero${guard ? " is-on" : ""}">
        <div class="card-content dash-hero-row">
          <div class="dash-hero-icon">${ic(guard ? "shield-check" : "shield-off")}</div>
          <div class="grow">
            <div class="dash-hero-title">${guard ? "Защита активна" : "Защита выключена"}</div>
            <div class="dash-hero-sub">
              ${n} из 4 модулей включено
              <span class="dash-sep"></span>
              ${admin ? `${ic("check")} права администратора` : `<span class="dash-warn">${ic("triangle-alert")} нет прав администратора</span>`}
            </div>
          </div>
          <div class="dash-hero-meter" aria-hidden="true">
            ${MODULES.map(m => `<span class="${m.on(Store.get(m.key)) ? "on" : ""}"></span>`).join("")}
          </div>
        </div>
      </div>`;
  }

  function moduleHtml(m) {
    const st = Store.get(m.key);
    const err = Store.error(m.key) || st?.error;
    const on = m.on(st);
    const pending = Store.get("dash.pending")?.[m.key];
    const blocked = m.blocked(st);
    return `
      <div class="card compact dash-mod${on ? " is-on" : ""}" data-key="mod-${m.key}">
        <div class="card-content dash-mod-top">
          <div class="dash-mod-icon">${ic(m.icon)}</div>
          <div class="grow">
            <div class="dash-mod-title">${m.title}</div>
            <div class="dash-mod-meta">${pending ? `<span class="muted">${on ? "Включается" : "Выключается"}…</span>` : (m.meta(st) || "&nbsp;")}</div>
          </div>
          ${switchHtml(on, `data-toggle="${m.key}"${blocked ? ` data-tip="${esc(blocked)}"` : ""}`, { disabled: !!blocked || !!pending, pending: !!pending })}
        </div>
        <div class="card-content dash-mod-foot">
          ${err ? `<span class="badge danger">${ic("circle-alert")}${esc(String(err).slice(0, 80))}</span>`
                : on ? `<span class="badge success"><span class="dot on"></span>Работает</span>`
                     : `<span class="badge outline muted">Выключено</span>`}
          <span class="dash-mod-extra">${m.foot(st) || ""}</span>
          <button class="btn ghost xs dash-open" data-go="${m.page}">Открыть ${ic("arrow-right")}</button>
        </div>
      </div>`;
  }

  function versionsHtml() {
    if (!versions) return "";
    const chips = versions.filter(s => s.kind !== "service").map(s =>
      `<div class="dash-ver"><span class="muted">${esc(s.name.split("(")[0].trim())}</span><b class="mono">${esc(s.version || "—")}</b></div>`).join("");
    return `
      <div class="card compact">
        <div class="card-header">
          <div class="card-title">${ic("package")}Компоненты</div>
          <div class="card-action"><button class="btn ghost xs" data-go="settings">Обновления ${ic("arrow-right")}</button></div>
        </div>
        <div class="card-content dash-vers">${chips}</div>
      </div>`;
  }

  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${heroHtml()}
      <div class="grid-2">${MODULES.map(moduleHtml).join("")}</div>
      ${versionsHtml()}`);
  }

  async function toggle(key) {
    const m = MODULES.find(x => x.key === key);
    const st = Store.get(key);
    if (!m || !st || m.blocked(st)) return;
    const target = !m.on(st);
    Store.set("dash.pending", { ...(Store.get("dash.pending") || {}), [key]: true });
    try {
      await optimistic(key, m.patch ? m.patch(target) : { running: target }, () => m.toggle(st, target),
        { errorTitle: `${m.title}: не удалось ${target ? "включить" : "выключить"}` });
    } catch { /* тост уже показан, стор откатен */ }
    finally {
      const p = { ...(Store.get("dash.pending") || {}) };
      delete p[key];
      Store.set("dash.pending", p);
    }
  }

  Pages.define({
    id: "dashboard", title: "Обзор", icon: "layout-dashboard", group: "",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Обзор</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;
      el.addEventListener("click", e => {
        const t = e.target.closest("[data-toggle]");
        if (t) return toggle(t.dataset.toggle);
        const go = e.target.closest("[data-go]");
        if (go) Pages.go(go.dataset.go);
      });
      api("upstream_versions").then(v => { versions = v; render(); }).catch(() => {});
    },
    show(ctx) {
      ctx.on(["winws", "proxy", "tg", "hosts", "app", "dash.pending"], render);
      render();
    },
  });
})();
