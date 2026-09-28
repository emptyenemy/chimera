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

  for (let i = 0; i < 150 && (typeof api !== "function" || typeof Bridge === "undefined"); i++) await sleep(100);

  await step("интерфейс загрузился", async () => {
    need(document.querySelector(".sidebar"), "нет сайдбара");
    need(document.querySelector(".sb-logo svg"), "нет логотипа");
    need(document.querySelectorAll("svg.icon").length > 5, "не отрисовались иконки");
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
  const skip = why => `пропуск: ${why}`;

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

  await step("настройки", async () => { await api("config_read"); });
  await step("автозапуск", async () => {
    const a = await api("autostart_get");
    need(a.supported, "автозапуск не поддерживается");
  });

  return JSON.stringify(out);
})()
