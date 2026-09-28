"use strict";
/* Оболочка вокруг страниц: подпись под логотипом, точки состояния у пунктов меню
   и строка прав/версии внизу сайдбара. Всё — из Store, без своих опросов. */

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
    const sub = $("#sb-sub");
    if (sub) sub.textContent = guard ? `Защита активна · ${n} из 4` : (n ? `${n} из 4 включено` : "Всё выключено");

    for (const [page, key] of Object.entries(dots)) {
      const el = document.querySelector(`[data-nav-dot="${page}"]`);
      if (!el) continue;
      const err = Store.error(key);
      el.className = "sb-dot dot" + (err ? " err" : Status[key]() ? " on" : "");
      el.hidden = !err && !Status[key]();
    }

    const app = Store.get("app") || {};
    morph($("#sb-status"), app.admin === false
      ? `<span class="dot warn"></span><span>Нет прав администратора</span>`
      : `<span class="dot on"></span><span>Администратор${app.version ? ` · v${esc(app.version)}` : ""}</span>`);

    // служба держит процессы сама — окно их не запускает и не гасит при выходе
    morph($("#sb-service"), app.service_running
      ? `<div class="sb-service" data-key="plank">${ic("server")}<span>Модулями управляет фоновая служба Chimera</span></div>`
      : "");
  }

  Store.on(["winws", "proxy", "tg", "hosts", "app"], render);
})();
