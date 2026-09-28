"use strict";
/* Обзор: общий статус защиты и быстрые тумблеры всех модулей.
   Эталон устройства страницы: рендер только из Store, morph() на каждое
   изменение, тумблеры — optimistic(), своих опросов нет. */

(() => {
  let root;

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
          : (name ? `Стратегия «${esc(name)}»` : "Стратегия не выбрана");
      },
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
        return st.parsed ? `${esc(st.parsed.server || "")} · ${mode}` : "";
      },
      toggle: (st, on) => api(on ? "proxy_start" : "proxy_stop"),
    },
    {
      key: "tg", page: "telegram", icon: "send", title: "Telegram-прокси",
      on: st => !!st?.running,
      blocked: st => st ? "" : "Загрузка…",
      meta: st => !st ? "" : `${esc(st.host || "127.0.0.1")}:${esc(st.port ?? "")}`,
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
        : (n => n ? `${n} ${plural(n, "сервис", "сервиса", "сервисов")} выбрано` : "")(
            new Set(Object.values(st.assignments || {}).flat()).size),
      toggle: (st, on) => api("hosts_set_enabled", on),
      // у hosts «включено» — это applied, а не running
      patch: on => ({ applied: on }),
    },
  ];

  function heroHtml() {
    const guard = Status.guard();
    const n = Status.count();
    return `
      <div class="card dash-hero${guard ? " is-on" : ""}">
        <div class="card-content dash-hero-row">
          <div class="dash-hero-icon">${ic(guard ? "shield-check" : "shield-off")}</div>
          <div class="grow">
            <div class="dash-hero-title">${guard ? "Защита активна" : "Защита выключена"}</div>
            <div class="dash-hero-sub">${n ? `Включено ${n} из 4` : "Включи нужные модули ниже"}</div>
          </div>
        </div>
      </div>`;
  }

  // Одна строка под названием: ошибка, если есть; почему не включить; иначе — суть модуля.
  function lineHtml(m, st, on, pending) {
    const err = Store.error(m.key) || st?.error;
    if (pending) return `<span class="muted">${on ? "Включается" : "Выключается"}…</span>`;
    if (err) return `<span class="dash-err">${esc(String(err).slice(0, 120))}</span>`;
    const blocked = m.blocked(st);
    if (blocked && !on) return `<span class="dash-blocked">${esc(blocked)}</span>`;
    const parts = [m.meta(st), m.key === "proxy" && st ? esc(proxyScope(st)) : ""].filter(Boolean);
    return parts.join(" · ") || "&nbsp;";
  }

  function moduleHtml(m) {
    const st = Store.get(m.key);
    const on = m.on(st);
    const pending = Store.get("dash.pending")?.[m.key];
    const blocked = m.blocked(st);
    return `
      <div class="card compact dash-mod${on ? " is-on" : ""}" data-key="mod-${m.key}" data-go="${m.page}">
        <div class="card-content dash-mod-row">
          <div class="dash-mod-icon">${ic(m.icon)}</div>
          <div class="grow">
            <div class="dash-mod-title">${m.title}</div>
            <div class="dash-mod-meta">${lineHtml(m, st, on, pending)}</div>
          </div>
          ${switchHtml(on, `data-toggle="${m.key}"`, { disabled: !!blocked || !!pending, pending: !!pending })}
        </div>
      </div>`;
  }

  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${heroHtml()}
      <div class="grid-2">${MODULES.map(moduleHtml).join("")}</div>`);
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
        // переключатель — сам по себе, остальная карточка ведёт на страницу модуля
        const t = e.target.closest("[data-toggle]");
        if (t) return t.disabled ? undefined : toggle(t.dataset.toggle);
        const go = e.target.closest("[data-go]");
        if (go) Pages.go(go.dataset.go);
      });
    },
    show(ctx) {
      ctx.on(["winws", "proxy", "tg", "hosts", "app", "dash.pending"], render);
      render();
    },
  });
})();
