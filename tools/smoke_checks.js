// Проверки дымового теста сборки (tools/smoke_build.py) — выполняются внутри
// страницы собранной программы и зовут те же api(), что и интерфейс. Цель —
// поймать то, что тестам исходников не видно: модуль или файл, который Nuitka
// не положила в exe. Ничего не меняют в системе: winws, TUN, hosts и DNS не
// трогаются; все записи — в копию сборки и её временную папку данных.
(async () => {
  const out = [];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const need = (cond, msg) => { if (!cond) throw new Error(msg); };
  async function step(name, fn, { network = false } = {}) {
    try {
      const d = await fn();
      out.push({ name, ok: true, detail: d === undefined ? "" : String(d) });
    } catch (e) {
      out.push({ name, ok: false, network, detail: String((e && e.message) || e) });
    }
  }

  for (let i = 0; i < 150 && (typeof api !== "function" || typeof Bridge === "undefined" || !document.querySelector('[data-testid="sidebar"]')); i++) await sleep(100);

  const skip = why => `пропуск: ${why}`;
  await step("интерфейс загрузился", async () => {
    need(document.querySelector('[data-testid="sidebar"]'), "нет сайдбара");
    need(document.querySelector('[data-testid="brand-logo"]'), "нет логотипа");
    need(document.querySelectorAll("svg.lucide").length > 5, "не отрисовались иконки");
    need(Pages.list.length === 9, "нет всех страниц");
    return "shadcn";
  });
  await step("все страницы", async () => {
    for (const page of Pages.list) {
      Pages.go(page.id);
      for (let i = 0; i < 50 && !document.querySelector(`[data-testid="page-${page.id}"]`); i++) await sleep(100);
      need(document.querySelector(`[data-testid="page-${page.id}"]`), `не открылась страница ${page.id}`);
    }
    return `${Pages.list.length} страниц`;
  });
  await step("языки", async () => {
    const state = await api("lang_get");
    for (const lang of ["ru", "en"]) {
      const data = await api("i18n_get", lang);
      need(data.lang === lang && data.catalog["err.admin.hosts"], "каталог не загружен");
    }
    return state.lang;
  });
  await step("app_info", async () => (await api("app_info")).version);
  await step("hub_snapshot", async () => Object.keys(await api("hub_snapshot")).join(","));

  // обход DPI: стратегии и fake-блобы (.bin) лежат рядом с exe
  await step("стратегии", async () => {
    const st = await api("winws_state");
    need(st.strategies?.length > 0, "список стратегий пуст");
    return `${st.strategies.length} шт.`;
  });
  await step("фильтры и fake-блобы", async () => {
    const f = await api("filters_state");
    need(f.fakes?.candidates?.length > 0, "нет .bin-блобов в strategies/assets");
    return `${f.fakes.candidates.length} блобов`;
  });
  // Программа считает «своим» и уже запущенный в системе winws2/sing-box (например,
  // у открытой рядом Chimera) и при изменении настроек перезапускает его. Тест не
  // должен трогать чужой обход — такие шаги при работающем модуле пропускаются.
  const winwsBusy = (await api("winws_state")).running;
  const proxyBusy = (await api("proxy_state")).running;

  await step("списки для стратегий", async () => {
    if (winwsBusy) return skip("winws2 уже работает в системе");
    await api("winws_set_lists", []);
  });
  await step("лог winws", async () => { await api("winws_log", 0); });

  // прокси: ядро sing-box, разбор ссылки, режимы, выбор приложений
  await step("ядро sing-box", async () => {
    const p = await api("proxy_state");
    need(p.core?.present, "sing-box.exe нет в сборке");
    return p.core.version;
  });
  await step("ссылка прокси", async () => {
    if (proxyBusy) return skip("sing-box уже работает в системе");
    const r = await api("proxy_set_link", "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1?type=tcp&security=none#smoke");
    need(r?.parsed?.protocol === "vless", "ссылка не разобрана");
  });
  await step("режимы прокси", async () => {
    if (proxyBusy) return skip("sing-box уже работает в системе");
    for (const m of ["split", "tun", "pac"]) await api("proxy_set_mode", m);
  });
  await step("запущенные программы", async () => `${(await api("proxy_apps_snapshot")).length} шт.`);

  // Telegram-прокси: ядро tg-ws-proxy импортируется во время работы — главное место,
  // где в сборке не хватало модулей; порт свой, чтобы не спорить с открытой программой
  await step("tg-прокси: запуск и остановка", async () => {
    const st = await api("tg_state");
    await api("tg_set_config", "127.0.0.1", 19443, st.secret, false);
    await api("tg_start");
    let running = false;
    for (let i = 0; i < 40 && !running; i++) { await sleep(150); running = (await api("tg_state")).running; }
    need(running, "не поднялся");
    await api("tg_stats");
    await api("tg_stop");
    need((await api("tg_state")).link?.startsWith("tg://"), "нет ссылки подключения");
  });

  // hosts: провайдеры, встроенный список Flowseal (файл hosts из upstream/)
  await step("hosts: провайдеры", async () => {
    const o = await api("hosts_overview");
    const flowseal = (o.providers || []).find(p => p.type === "static");
    need(flowseal, "нет встроенного провайдера Flowseal");
    need(flowseal.available !== false, `Flowseal недоступен: ${flowseal.reason || ""}`);
    return `${o.providers.length} провайдеров`;
  });
  await step("hosts: состояние", async () => { await api("hosts_state"); });

  // DNS
  await step("DNS: адаптеры", async () => {
    const d = await api("dns_state");
    need(d.adapters?.length > 0, "адаптеры не найдены");
    return `${d.adapters.length} адаптеров`;
  });
  await step("DNS: настройки пробы", async () => { await api("dns_probe_config"); });
  await step("DNS: пинг провайдеров", async () => { await api("dns_ping"); }, { network: true });

  // списки: встроенные на месте, свой создаётся/правится/переименовывается/удаляется
  await step("списки: встроенные", async () => {
    const all = await api("lists_all");
    need(all.length > 0, "встроенных списков нет");
    need((await api("lists_read", all[0].name ?? all[0])) !== undefined, "список не читается");
    return `${all.length} шт.`;
  });
  await step("списки: свой", async () => {
    await api("lists_create", "smoke-test");
    await api("lists_save", "smoke-test", "example.com\n");
    await api("lists_rename", "smoke-test", "smoke-test-2");
    await api("lists_delete", "smoke-test-2");
  });

  // проверки доступности
  await step("проверка домена", async () => { await api("block_check_one", "example.com"); }, { network: true });
  await step("реестр РКН", async () => { await api("chebur_status"); }, { network: true });

  // страница «Проверка сайтов» целиком: список -> две потоковые проверки на бэкенде ->
  // пуши -> сведённая таблица; самый короткий список, чтобы не ждать
  let listSmokeName = "";
  await step("проверка сайтов: выбор списка", async () => {
    Pages.go("checks");
    for (let i = 0; i < 50 && !document.querySelector('[data-testid="checks-list"]'); i++) await sleep(100);
    const trigger = document.querySelector('[data-testid="checks-list"]');
    need(trigger, "нет выбора списка");
    const lists = await api("lists_all");
    const small = [...lists].filter(l => l.count > 0).sort((a, b) => a.count - b.count)[0];
    need(small, "нет непустых списков");
    trigger.click();
    for (let i = 0; i < 50 && !document.querySelector(`[data-testid="checks-list-${small.name}"]`); i++) await sleep(100);
    const option = document.querySelector(`[data-testid="checks-list-${small.name}"]`);
    need(option, "не открылся список shadcn");
    option.click();
    listSmokeName = small.name;
    return small.name;
  });
  await step("проверка сайтов: поток результатов", async () => {
    need(listSmokeName, "список не выбран");
    for (let i = 0; i < 300 && !document.querySelector('[data-testid="checks-summary"]'); i++) await sleep(200);
    const summary = document.querySelector('[data-testid="checks-summary"]')?.textContent || "";
    need(summary, "проверка не закончилась");
    const rows = document.querySelectorAll('[data-testid^="checks-row-"]').length;
    need(rows > 0, "таблица результатов пустая");
    return `${listSmokeName}: ${summary}`;
  }, { network: true });

  // источники и обновление программы
  await step("версии компонентов", async () => {
    const v = await api("upstream_versions");
    const git = v.filter(s => s.kind === "tag" || s.kind === "commit");
    const empty = git.filter(s => !s.version || s.version === "—").map(s => s.name);
    need(!empty.length, `нет версий: ${empty.join(", ")}`);
  });
  await step("самообновление: состояние", async () => {
    const s = await api("selfupdate_state");
    need(s.frozen === true, "сборка не распознала себя собранной");
    return s.current;
  });
  await step("самообновление: проверка", async () => { await api("selfupdate_check"); }, { network: true });

  // --- полный режим (tools/smoke_build.py --full, только CI/одноразовые машины) ------
  // Всё, что требует прав администратора и меняет систему: каждый шаг возвращает её
  // как было. Без прав или без флага — пропуск.
  const full = window.__SMOKE_FULL__ === true && (await api("app_info")).admin === true;
  const fullStep = (name, fn) => step(name, async () => (full ? fn() : skip("нужен --full и права администратора")));
  const until = async (fn, what, tries = 60) => {
    for (let i = 0; i < tries; i++) { if (await fn()) return; await sleep(250); }
    throw new Error(`не дождался: ${what}`);
  };

  await fullStep("обход DPI: запуск и остановка", async () => {
    const st = await api("winws_state");
    await api("winws_start", st.strategies[0].id);
    await until(async () => (await api("winws_state")).running, "winws2 запущен");
    await api("winws_stop");
    await until(async () => !(await api("winws_state")).running, "winws2 остановлен");
  });

  await fullStep("hosts: применение и снятие", async () => {
    const o = await api("hosts_overview");
    const flowseal = o.providers.find(p => p.type === "static");
    await api("hosts_set_assignments", { [flowseal.id]: true });
    await api("hosts_set_enabled", true);
    await until(async () => (await api("hosts_state")).applied, "записи в hosts");
    await api("hosts_set_enabled", false);
    await api("hosts_set_assignments", {});
    await until(async () => !(await api("hosts_state")).applied, "hosts очищен");
  });

  for (const mode of ["pac", "split", "tun"]) {
    await fullStep(`прокси: запуск и остановка (${mode})`, async () => {
      if (proxyBusy) return skip("sing-box уже работает в системе");
      await api("proxy_set_link", "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1?type=tcp&security=none#smoke");
      await api("proxy_set_lists", ["youtube"]);
      await api("proxy_set_mode", mode);
      await api("proxy_start");
      await until(async () => (await api("proxy_state")).running, "sing-box запущен");
      await api("proxy_stop");
      await until(async () => !(await api("proxy_state")).running, "sing-box остановлен");
    });
  }

  await fullStep("DNS: смена и сброс", async () => {
    const d = await api("dns_state");
    const a = d.adapters.find(x => x.dns?.length) || d.adapters[0];
    await api("dns_set", a.index, "cloudflare");
    await api("dns_reset", a.index);
  });

  await fullStep("автозапуск с Windows: включить и выключить", async () => {
    const on = await api("autostart_set", true);
    need(on.enabled && on.supported, "задача не создалась");
    const off = await api("autostart_set", false);
    need(!off.enabled && off.supported, "задача не удалилась");
  });

  await step("настройки", async () => { await api("config_read"); });
  await step("палитры и акцент готового exe", async () => {
    const original = await api("appearance_state");
    need(original.themes.length >= 14, "каталог тем не упакован");
    const changed = await api("appearance_apply", { theme: "dark", appearance: { palette: "catppuccin-mocha", accent_source: "custom", accent: "#00ff00" } });
    need(changed.normalized && changed.contrast.text >= 4.5 && changed.contrast.background >= 4.5, "небезопасный акцент");
    for (let i = 0; i < 100 && document.documentElement.dataset.palette !== "catppuccin-mocha"; i++) await sleep(100);
    need(document.documentElement.dataset.palette === "catppuccin-mocha", "тема не поменялась в нативном окне");
    await api("appearance_apply", original.settings);
    return "каталог, нормализация, контраст, смена без перезапуска";
  });
  await step("автозапуск", async () => {
    const a = await api("autostart_get");
    need(a.supported, "автозапуск не поддерживается");
  });

  return JSON.stringify(out);
})()
