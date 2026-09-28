"use strict";
/* Оболочка вокруг страниц: версия под логотипом, точки состояния у пунктов меню
   и строка состояния защиты/прав внизу сайдбара. Всё — из Store, без своих опросов. */

// «Включён ли модуль» — одно место, чтобы дашборд, меню и подписи не разъезжались.
const Status = {
  winws: () => !!Store.get("winws")?.running,
  proxy: () => !!Store.get("proxy")?.running,
  tg: () => !!Store.get("tg")?.running,
  hosts: () => !!Store.get("hosts")?.applied,
  // «защита» — любой способ обхода, который реально трогает трафик
  guard() { return this.winws() || this.proxy() || this.hosts(); },
  count() { return [this.winws(), this.proxy(), this.tg(), this.hosts()].filter(Boolean).length; },
};

(() => {
  // страница -> от чего горит её точка в меню
  const dots = { strategies: "winws", proxy: "proxy", telegram: "tg", hosts: "hosts" };

  function render() {
    const guard = Status.guard();
    const n = Status.count();
    const app = Store.get("app") || {};
    const ver = $("#sb-ver");
    if (ver) ver.textContent = fmtVersion(app.version);

    for (const [page, key] of Object.entries(dots)) {
      const el = document.querySelector(`[data-nav-dot="${page}"]`);
      if (!el) continue;
      const err = Store.error(key);
      el.className = "sb-dot dot" + (err ? " err" : Status[key]() ? " on" : "");
      el.hidden = !err && !Status[key]();
    }

    // Шапка — только знак, название и версия; состояние живёт внизу, в строке статуса.
    // «Администратор» не пишем: это норма, строка появляется только когда прав нет.
    const state = guard ? `Защита активна · ${n} из 4` : (n ? `${n} из 4 включено` : "Всё выключено");
    const noAdmin = "Нет прав администратора";
    morph($("#sb-status"),
      `<div class="sb-status-row" data-tip-rail="${state}"><span class="dot${guard ? " on" : ""}"></span><span>${state}</span></div>` +
      (app.admin === false
        ? `<div class="sb-status-row" data-tip-rail="${noAdmin}"><span class="dot warn"></span><span>${noAdmin}</span></div>` : ""));

    // служба держит процессы сама — окно их не запускает и не гасит при выходе
    const plank = "Модулями управляет фоновая служба Chimera";
    morph($("#sb-service"), app.service_running
      ? `<div class="sb-service" data-key="plank" data-tip-rail="${plank}">${ic("server")}<span>${plank}</span></div>`
      : "");
  }

  Store.on(["winws", "proxy", "tg", "hosts", "app"], render);
})();

// --- Сворачивание и ширина сайдбара ---------------------------------------------------
// Класс sb-collapsed и переменная --sb-w на <html> (их же ставит скрипт в <head> до
// первой отрисовки), состояние — в localStorage "chimera.sidebar". Ctrl+B — как у
// сайдбара shadcn. Ресайз двигает только --sb-w: страницы не перерисовываются.

const Sidebar = (() => {
  const KEY = "chimera.sidebar";
  const root = document.documentElement;

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; }
  }
  function save(patch) {
    try { localStorage.setItem(KEY, JSON.stringify({ ...load(), ...patch })); } catch {}
  }

  const collapsed = () => root.classList.contains("sb-collapsed");
  function setCollapsed(on) {
    root.classList.toggle("sb-collapsed", on);
    $("#sb-toggle")?.setAttribute("aria-label", on ? "Развернуть панель" : "Свернуть панель");
    save({ collapsed: on });
  }
  const toggle = () => setCollapsed(!collapsed());

  $("#sb-toggle")?.addEventListener("click", toggle);
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.code === "KeyB") { e.preventDefault(); toggle(); }
  });
  if (collapsed()) setCollapsed(true);  // подпись кнопки — под состояние, поднятое в <head>

  // ширина: дефолт как в .app (232px), тянуть меньше SNAP — значит свернуть в полосу
  const W_DEF = 232, W_MIN = 180, W_MAX = 360, SNAP = 120;
  const clamp = w => Math.round(Math.min(W_MAX, Math.max(W_MIN, w)));
  const width = () => parseFloat(getComputedStyle(root).getPropertyValue("--sb-w")) || W_DEF;
  const setWidth = w => root.style.setProperty("--sb-w", w + "px");

  const handle = $("#sb-resize");
  let drag = null;
  handle?.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    // wOpen — ширина развёрнутой панели до начала: к ней вернёмся, если утащат в полосу
    drag = { x0: e.clientX, w0: collapsed() ? 48 : width(), wOpen: width(), x: e.clientX, raf: 0 };
    root.classList.add("sb-resizing");
  });
  handle?.addEventListener("pointermove", e => {
    if (!drag) return;
    drag.x = e.clientX;
    // не чаще раза в кадр: pointermove сыплет быстрее, чем браузер успевает перекладку
    drag.raf ||= requestAnimationFrame(() => {
      drag.raf = 0;
      const raw = drag.w0 + drag.x - drag.x0;
      if (raw < SNAP) {
        setWidth(drag.wOpen);  // по пути через минимум ширина прижалась к W_MIN — откатываем
        if (!collapsed()) setCollapsed(true);
        return;
      }
      if (collapsed()) setCollapsed(false);
      setWidth(clamp(raw));
    });
  });
  const stop = () => {
    if (!drag) return;
    cancelAnimationFrame(drag.raf);
    drag = null;
    root.classList.remove("sb-resizing");
    save({ width: width() });
  };
  handle?.addEventListener("pointerup", stop);
  handle?.addEventListener("pointercancel", stop);
  // двойной клик — ширина по умолчанию (и развернуть, если панель была свёрнута)
  handle?.addEventListener("dblclick", () => {
    root.style.removeProperty("--sb-w");
    save({ width: null });
    if (collapsed()) setCollapsed(false);
  });

  return { load, save, collapsed, setCollapsed, toggle, width, setWidth };
})();
