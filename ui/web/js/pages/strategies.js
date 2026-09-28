"use strict";
/* Стратегии — обход DPI: zapret2/winws2. Состояние — Store.get("winws") (хаб,
   опрашивается всегда) + Store.get("filters") (ленивый ключ, включаем в show()).
   Список стратегий может быть длинным — поиск по имени/описанию, выбранная
   строка подсвечена, клик по строке во время работы сразу переключает стратегию. */

(() => {
  let root;
  let selected = null;   // стратегия, выбранная пользователем (не обязательно запущенная)
  let search = "";
  const busy = new Set();  // ключи операций в полёте — управляют спиннерами/disabled в render()

  const GAME_RANGE_DEFAULT = "1024-65535";
  const gameRangeErr = { tcp: null, udp: null };  // текст ошибки под полем (null — поле в порядке)

  function render() {
    const st = Store.get("winws");
    const f = Store.get("filters");
    const admin = Store.get("app")?.admin !== false;
    if (st) selected = st.current || selected || st.last_strategy || st.strategies?.[0]?.id || null;
    morph(root.querySelector("[data-slot=status]"), statusHtml(st, admin));
    morph(root.querySelector("[data-slot=rows]"), rowsHtml(st));
    morph(root.querySelector("[data-slot=lists]"), listsHtml(st));
    morph(root.querySelector("[data-slot=filters]"), filtersHtml(f));
  }

  async function runBusy(key, fn) {
    busy.add(key); render();
    try { return await fn(); }
    finally { busy.delete(key); render(); }
  }

  const wdLingers = st => !!st && !st.running && st.windivert === "RUNNING";

  // --- статус / пуск-стоп -------------------------------------------------------

  function statusHtml(st, admin) {
    if (!st) return `<div class="card compact"><div class="card-content">${skeletonHtml(3, 24)}</div></div>`;
    const lingers = wdLingers(st);
    const on = st.running || lingers;
    const tone = st.running ? "on" : lingers ? "warn" : "off";
    const stratName = st.strategies?.find(s => s.id === (st.current || selected))?.name;

    // одна строка: что сейчас происходит; подробности — только когда они что-то меняют
    const title = st.external ? "Работает (запущен вне Chimera)"
      : st.running ? `Работает · ${esc(stratName || st.current || "?")}`
      : lingers ? "Остановлено · драйвер ещё загружен" : "Остановлено";

    const label = lingers ? "Выгрузить драйвер" : st.running ? "Остановить" : "Запустить";
    const noAdmin = !on && !admin;
    const disabled = (!on && !selected) || noAdmin;
    const working = busy.has("toggle");
    const tip = noAdmin ? "Нужны права администратора" : !on && !selected ? "Сначала выбери стратегию" : "";

    return `
      <div class="card compact strat-status${tone === "on" ? " is-on" : ""}">
        <div class="card-content strat-status-row">
          <span class="dot ${tone === "on" ? "on" : tone === "warn" ? "warn" : ""}"></span>
          <div class="grow strat-status-title">${title}</div>
          <label class="strat-autostart"><span class="muted">Автозапуск</span>${switchHtml(!!st.autostart, "data-autostart")}</label>
          <button type="button" class="btn sm${on ? " destructive" : ""}${working ? " busy" : ""}" data-toggle-winws
            ${disabled || working ? "disabled" : ""} ${tip && !working ? `data-tip="${tip}"` : ""}>
            ${working ? ic("loader-circle") : ""}${esc(label)}
          </button>
        </div>
        ${st.error ? `<div class="card-content"><div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(st.error)}</div></div></div>` : ""}
      </div>`;
  }

  async function toggleWinws() {
    if (busy.has("toggle")) return;
    const st = Store.get("winws");
    if (!st) return;
    const lingers = wdLingers(st);
    await runBusy("toggle", async () => {
      try {
        if (st.running || lingers) {
          await optimistic("winws", { running: false, current: null }, () => api("winws_stop"),
            { errorTitle: "Не удалось остановить zapret2" });
          toast.success(lingers ? "Драйвер WinDivert выгружен." : "zapret2 остановлен.");
        } else {
          if (!selected) return;
          await optimistic("winws", { running: true, current: selected }, () => api("winws_start", selected),
            { errorTitle: "Не удалось запустить zapret2" });
          toast.success("zapret2 запущен.");
        }
      } catch { /* тост уже показан optimistic() */ }
    });
  }

  async function selectStrategy(id) {
    if (busy.has("toggle") || busy.has("switch")) return;
    const st = Store.get("winws");
    if (!st) return;
    selected = id;
    if (st.running && id !== st.current) {
      await runBusy("switch", async () => {
        try {
          await optimistic("winws", { current: id, running: true }, () => api("winws_start", id),
            { errorTitle: "Не удалось переключить стратегию" });
          toast.success("Стратегия переключена.");
        } catch { /* тост уже показан */ }
      });
    } else {
      render();
    }
  }

  function onAutostart(v) {
    optimistic("winws", { autostart: v }, () => api("winws_set_autostart", v),
      { errorTitle: "Автозапуск: не получилось изменить" }).catch(() => {});
  }

  // --- список стратегий -----------------------------------------------------

  function rowsHtml(st) {
    if (!st) return skeletonHtml(6, 56);
    if (!st.strategies?.length) return emptyHtml({ icon: "shield", title: "Стратегий нет", desc: "Файлы .txt не найдены в strategies/." });
    const q = search.trim().toLowerCase();
    const list = q ? st.strategies.filter(s => s.name.toLowerCase().includes(q) || (s.desc || "").toLowerCase().includes(q)) : st.strategies;
    if (!list.length) return emptyHtml({ icon: "search", title: "Ничего не найдено", desc: `По запросу «${search}» стратегий нет.` });
    return `<div class="strat-grid" data-key="rows">${list.map(s => rowHtml(s, st)).join("")}</div>`;
  }

  // Плитка стратегии: только имя; что внутри (fake/split/…) — во всплывающей подсказке,
  // пользователю это нужно разве что для сравнения, а не каждый раз перед глазами
  function rowHtml(s, st) {
    const isRun = s.id === st.current;
    const isSel = s.id === selected;
    return `
      <button type="button" class="strat-row${isRun ? " is-run" : ""}" data-key="s-${esc(s.id)}" data-id="${esc(s.id)}"
        ${isSel ? 'aria-selected="true"' : ""} ${s.desc ? `data-tip="${esc(s.desc)}"` : ""}>
        ${isRun ? '<span class="dot on"></span>' : ""}<span class="strat-name">${esc(s.name)}</span>
      </button>`;
  }

  // --- списки для маршрутизации через winws ----------------------------------

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
      <div class="strat-lists-grid" data-key="grid">
        ${all.map(n => `
          <label class="check-row" data-key="l-${esc(n)}">
            <input type="checkbox" class="checkbox" value="${esc(n)}" ${sel.has(n) ? "checked" : ""}>
            <span>${esc(n)}</span>
          </label>`).join("")}
      </div>`;
  }

  function onListsToggle() {
    const names = $$(".strat-lists-grid input:checked", root).map(c => c.value);
    optimistic("winws", { lists: names }, () => api("winws_set_lists", names),
      { errorTitle: "Списки: не удалось сохранить" }).catch(() => {});
  }

  // --- фильтры (game / ipset / fake) -----------------------------------------

  function segHtml(items, current, attr) {
    return `<div class="tabs-list">${items.map(([mode, label]) => `
      <button type="button" class="tabs-trigger" data-${attr}="${mode}" aria-selected="${mode === current}">${esc(label)}</button>
    `).join("")}</div>`;
  }

  function fakeSlotsHtml(f) {
    const fakes = f?.fakes;
    if (!fakes || !fakes.candidates?.length) return `<p class="hint">Блобов в strategies/assets нет.</p>`;
    return `<div class="strat-fake-slots">${Object.entries(fakes.slots).map(([slot, s]) => {
      const custom = s.present && !s.current ? `<option value="" selected>свой файл</option>` : "";
      const opts = fakes.candidates.map(name => `<option value="${esc(name)}"${name === s.current ? " selected" : ""}>${esc(name)}</option>`).join("");
      return `<div class="field strat-fake-slot" data-key="fake-${esc(slot)}">
        <label class="label">${esc(s.label)}</label>
        <select class="select-native sm" data-fake-slot="${esc(slot)}">${custom}${opts}</select>
      </div>`;
    }).join("")}</div>`;
  }

  function gameRangeFieldHtml(which, value, enabled) {
    const err = gameRangeErr[which];
    const label = which === "tcp" ? "TCP-порты" : "UDP-порты";
    return `
      <div class="field strat-game-field" data-key="gr-${which}">
        <label class="label muted">${label}</label>
        <input class="input mono sm" data-game-range="${which}" value="${esc(value)}"
          ${enabled ? "" : "disabled"} ${err ? 'aria-invalid="true"' : ""} spellcheck="false">
        ${err ? `<p class="hint strat-game-err">${esc(err)}</p>` : ""}
      </div>`;
  }

  function filtersHtml(f) {
    if (!f) return skeletonHtml(4, 40);
    const ipsetNote = f.ipset === "loaded"
      ? `${fmtNum(f.ipset_count)} ${plural(f.ipset_count, "подсеть", "подсети", "подсетей")}`
      : (f.ipset_stored ? `${fmtNum(f.ipset_stored)} в запасе` : "");
    const updating = busy.has("ipsetUpdate");
    const ranges = f.game_ranges || { tcp: GAME_RANGE_DEFAULT, udp: GAME_RANGE_DEFAULT };
    const tcpOn = f.game === "all" || f.game === "tcp";
    const udpOn = f.game === "all" || f.game === "udp";
    return `
      <div class="strat-filter-row" data-key="game">
        <div class="between">
          <div class="label">Игры</div>
          ${segHtml([["off", "Выкл"], ["all", "TCP+UDP"], ["tcp", "TCP"], ["udp", "UDP"]], f.game, "game")}
        </div>
        ${f.game !== "off" ? `
        <div class="strat-game-ranges">
          ${gameRangeFieldHtml("tcp", ranges.tcp, tcpOn)}
          ${gameRangeFieldHtml("udp", ranges.udp, udpOn)}
          <button type="button" class="btn outline sm" data-game-range-default>${ic("rotate-ccw")}По умолчанию</button>
        </div>` : ""}
      </div>
      <div class="separator"></div>
      <div class="between strat-filter-row" data-key="ipset">
        <div class="label">Фильтр по IP${ipsetNote ? ` <span class="muted">· ${ipsetNote}</span>` : ""}</div>
        <div class="cluster">
          ${segHtml([["none", "Нет"], ["any", "Любой IP"], ["loaded", "Список"]], f.ipset, "ipset")}
          <button type="button" class="btn outline sm${updating ? " busy" : ""}" data-ipset-update ${updating ? "disabled" : ""}>
            ${updating ? ic("loader-circle") : ic("refresh-cw")}Обновить
          </button>
        </div>
      </div>
      <div class="separator"></div>
      <div class="strat-filter-row" data-key="fakes">
        ${fakeSlotsHtml(f)}
      </div>`;
  }

  // Перезапуск запущенной стратегии после смены фильтра делает бэкенд (Api), чтобы то же
  // самое получал CLI и агент; здесь только итог для пользователя.
  function reportApply(label, res) {
    if (res?.apply_error) { toast.error(`Не удалось применить: ${label}`, res.apply_error); return; }
    if (Store.get("winws")?.running) toast.success(`${label} применён — стратегия перезапущена.`);
  }

  async function setGameMode(mode) {
    let res;
    try { res = await optimistic("filters", { game: mode }, () => api("game_filter_set", mode), { errorTitle: "Game-фильтр: не удалось изменить" }); }
    catch { return; }
    reportApply("Game-фильтр", res);
  }

  // Формат диапазона — зеркало modules/winws/filters.py:validate_game_range.
  // Проверяем на месте (мгновенная подсказка, без похода на бэкенд за очевидной
  // опечаткой); финальное слово всё равно за бэкендом — его отказ ловит catch ниже.
  const GAME_RANGE_ITEM_RE = /^[1-9][0-9]{0,4}(-[1-9][0-9]{0,4})?$/;
  function validateGameRangeLocal(value) {
    const s = value.replace(/\s+/g, "");
    if (!s) return "Диапазон портов не может быть пустым";
    for (const item of s.split(",")) {
      if (!GAME_RANGE_ITEM_RE.test(item)) return `Неверный формат: «${item}» (пример: 1024-1934,1936-65535)`;
      const [startS, endS] = item.split("-");
      const start = parseInt(startS, 10), end = parseInt(endS ?? startS, 10);
      if (start > 65535 || end > 65535) return `Порт вне диапазона 1..65535: «${item}»`;
      if (start > end) return `Начало диапазона больше конца: «${item}»`;
    }
    return null;
  }

  // Сохранение одного диапазона (tcp или udp) по Enter/blur. Ошибку показываем
  // у самого поля, а не тостом (тост на опечатку посреди набора был бы навязчив,
  // как и у ссылки прокси).
  async function saveGameRange(which, value) {
    const f = Store.get("filters");
    if (!f) return;
    value = (value ?? "").trim();
    if (value === (f.game_ranges?.[which] || "")) return;  // не менялось
    const localErr = validateGameRangeLocal(value);
    if (localErr) { gameRangeErr[which] = localErr; render(); return; }
    let res;
    try {
      const args = which === "tcp" ? [f.game, value, undefined] : [f.game, undefined, value];
      res = await api("game_filter_set", ...args);
      gameRangeErr[which] = null;
      Store.patch("filters", res);
      render();
    } catch (e) {
      gameRangeErr[which] = e.message;
      render();
      return;
    }
    reportApply(which === "tcp" ? "TCP-порты игр" : "UDP-порты игр", res);
  }

  async function resetGameRanges() {
    const f = Store.get("filters");
    if (!f) return;
    let res;
    try {
      res = await api("game_filter_set", f.game, GAME_RANGE_DEFAULT, GAME_RANGE_DEFAULT);
      gameRangeErr.tcp = null; gameRangeErr.udp = null;
      Store.patch("filters", res);
      render();
    } catch (e) { toast.error("Не удалось сбросить диапазоны", e.message); return; }
    reportApply("Диапазоны портов игр", res);
  }

  async function setIpsetMode(mode) {
    try { await optimistic("filters", { ipset: mode }, () => api("ipset_set", mode), { errorTitle: "IPSet: не удалось изменить" }); }
    catch { return; }
    // winws2 сам перечитывает ipset при изменении файла — перезапуск не нужен
  }

  async function updateIpset() {
    if (busy.has("ipsetUpdate")) return;
    await runBusy("ipsetUpdate", async () => {
      try {
        const r = await api("ipset_update");
        toast.success("Список IPSet обновлён", `${fmtNum(r.downloaded)} ${plural(r.downloaded, "подсеть", "подсети", "подсетей")} в запасе`);
      } catch (e) { toast.error("Не удалось обновить список", e.message); }
    });
  }

  async function setFake(slot, name) {
    if (!name) { render(); return; }  // выбран псевдо-пункт «свой файл» — менять нечего, вернуть селект к факту
    let res;
    try { res = await optimistic("filters", null, () => api("fake_set", slot, name), { errorTitle: "Фейк: не удалось изменить" }); }
    catch { return; }
    reportApply("Фейк", res);
  }

  // --- монтаж -----------------------------------------------------------------

  let log;

  Pages.define({
    id: "strategies", title: "Стратегии", icon: "shield", group: "Обход",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Стратегии</h1>
          </div>
        </div>
        <div class="stack">
          <div data-slot="status"></div>

          <div class="card">
            <div class="card-header">
              <div class="card-title">${ic("list-checks")}Стратегия</div>
              <div class="card-action">
                <div class="input-group strat-search">
                  ${ic("search")}
                  <input class="input sm" type="search" placeholder="Поиск" data-search value="">
                </div>
              </div>
            </div>
            <div class="card-content" data-slot="rows"></div>
          </div>

          <div class="card">
            <div class="card-header"><div class="card-title">${ic("list")}Списки сайтов</div></div>
            <div class="card-content" data-slot="lists"></div>
          </div>

          ${foldHtml("sliders-horizontal", "Дополнительно", '<div class="stack" data-slot="filters"></div>')}
          ${foldHtml("terminal", "Логи", '<pre class="log" data-log></pre>')}
        </div>`;

      el.addEventListener("click", e => {
        if (e.target.closest("[data-toggle-winws]")) return toggleWinws();
        const sw = e.target.closest("[data-autostart]");
        if (sw) return onAutostart(sw.getAttribute("aria-checked") !== "true");
        const row = e.target.closest(".strat-row");
        if (row) return selectStrategy(row.dataset.id);
        const go = e.target.closest("[data-go]");
        if (go) return Pages.go(go.dataset.go);
        const gm = e.target.closest("[data-game]");
        if (gm) return setGameMode(gm.dataset.game);
        const im = e.target.closest("[data-ipset]");
        if (im) return setIpsetMode(im.dataset.ipset);
        if (e.target.closest("[data-ipset-update]")) return updateIpset();
        if (e.target.closest("[data-game-range-default]")) return resetGameRanges();
      });
      el.addEventListener("input", e => {
        if (e.target.matches("[data-search]")) { search = e.target.value; render(); }
      });
      el.addEventListener("change", e => {
        if (e.target.closest(".strat-lists-grid")) return onListsToggle();
        if (e.target.matches("[data-fake-slot]")) return setFake(e.target.dataset.fakeSlot, e.target.value);
      });
      // blur — не всплывает, слушаем в фазе перехвата; Enter просто снимает фокус (дальше сработает blur)
      el.addEventListener("blur", e => {
        if (e.target.matches("[data-game-range]")) saveGameRange(e.target.dataset.gameRange, e.target.value);
      }, true);
      el.addEventListener("keydown", e => {
        if (e.key === "Enter" && e.target.matches("[data-game-range]")) e.target.blur();
      });

      log = new LogView(el.querySelector("[data-log]"), "winws_log");
    },
    show(ctx) {
      ctx.watch(["filters"]);
      ctx.on(["winws", "filters", "app"], render);
      log.attach(ctx);
      render();
    },
  });
})();
