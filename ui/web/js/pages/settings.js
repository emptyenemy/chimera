"use strict";
/* Настройки: движок интерфейса, права запуска и версии внешних компонентов
   (сабмодули, пиннутые бинари, Python, онлайн-сервис реестра). Ничего из
   этого не лежит в хабе — состояние читается на show() и живёт локально
   на странице, повторный вход рисует кэш сразу и обновляет в фоне. */

(() => {
  let root;
  let config = null;          // config.json (interface, ui_backend, auto_elevate)
  let autostart = null;       // {enabled, supported} — задача в планировщике Windows
  let sources = null;         // upstream.versions() / check_updates()
  let sourcesChecked = false; // сверяли ли уже с GitHub в этой сессии
  const cfgPending = {};      // ключ config.json -> идёт сохранение
  const srcBusy = new Map();  // имя источника -> "check" | "update"
  let autostartPending = false;

  const ENGINES = [
    { id: "pyside6", title: "Приложение" },
    // dev: в собранную программу pywebview не входит (build.bat) — там варианта нет
    { id: "pywebview", title: "Лёгкое окно (WebView2)", dev: true },
    { id: "browser", title: "Вкладка браузера" },
  ];

  // --- сеть / бэкенд ------------------------------------------------------------

  async function refreshConfig() {
    try { config = await api("config_read"); } catch (e) { toast.error("Не удалось прочитать настройки", e.message); }
    render();
  }

  async function refreshAutostart() {
    try { autostart = await api("autostart_get"); } catch { /* тумблер останется как был */ }
    render();
  }

  async function refreshSources() {
    try { sources = await api("upstream_versions"); } catch (e) { toast.error("Не удалось прочитать версии источников", e.message); }
    render();
  }

  async function setConfig(key, value) {
    if (!config || config[key] === value) return;
    const prev = config[key];
    config = { ...config, [key]: value };
    cfgPending[key] = true;
    render();
    try {
      config = (await api("config_set", key, value)) || config;
    } catch (e) {
      config = { ...config, [key]: prev };
      toast.error("Не удалось сохранить", e.message);
    } finally {
      delete cfgPending[key];
      render();
    }
  }

  async function toggleAutostart() {
    if (!autostart || !autostart.supported || autostartPending) return;
    const target = !autostart.enabled;
    autostartPending = true;
    autostart = { ...autostart, enabled: target };
    render();
    try {
      autostart = { ...autostart, ...(await api("autostart_set", target)) };
      toast.success(autostart.enabled ? "Автозапуск с Windows включён" : "Автозапуск с Windows выключен");
    } catch (e) {
      autostart = { ...autostart, enabled: !target };
      toast.error("Не удалось изменить автозапуск", e.message);
    } finally {
      autostartPending = false;
      render();
    }
  }

  function mergeSource(s) {
    if (!s) return;
    if (!sources) sources = [];
    const i = sources.findIndex(x => x.name === s.name);
    if (i >= 0) sources[i] = s; else sources.push(s);
  }

  async function checkOne(name) {
    if (srcBusy.has(name)) return;
    srcBusy.set(name, "check");
    render();
    try {
      const s = await api("upstream_check_one", name);
      if (!s) return;
      mergeSource(s);
      if (s.error) toast.error(`${name}: ${s.error}`);
      else if (s.update) toast.info(`${name}: доступно обновление ${s.latest}`);
      else toast.success(`${name}: актуально`);
    } catch (e) {
      toast.error(`${name}: не удалось проверить`, e.message);
    } finally {
      srcBusy.delete(name);
      render();
    }
  }

  async function checkAllSources() {
    if (!sources) return;
    sources.forEach(s => { if (!srcBusy.has(s.name)) srcBusy.set(s.name, "check"); });
    render();
    try {
      sources = (await api("upstream_check_updates")) || sources;
      sourcesChecked = true;
      const n = (sources || []).filter(s => s.update).length;
      n ? toast.info(`Есть обновления: ${n}`) : toast.success("Всё актуально");
    } catch (e) {
      toast.error("Не удалось проверить источники", e.message);
    } finally {
      sources?.forEach(s => srcBusy.delete(s.name));
      render();
    }
  }

  async function updateSource(name, quiet) {
    if (srcBusy.has(name)) return false;
    srcBusy.set(name, "update");
    render();
    let ok = false;
    try {
      const s = await api("upstream_update", name);
      mergeSource(s);
      ok = true;
      if (!quiet) toast.success(`${name}: ${s?.note || "обновлено"}`);
    } catch (e) {
      toast.error(`${name}: не удалось обновить`, e.message);
    } finally {
      srcBusy.delete(name);
      render();
    }
    return ok;
  }

  async function updateOneConfirm(name) {
    if (srcBusy.has(name)) return;
    const extra = name === "Стратегии (Flowseal)" ? " Стратегии будут перегенерированы под новые хостлисты." : "";
    const ok = await confirmDialog({
      title: `Обновить «${name}»?`,
      description: `Подтянуть свежую версию из репозитория (git fetch).${extra}`,
      confirmText: "Обновить",
    });
    if (ok) await updateSource(name);
  }

  async function updateAllConfirm() {
    if (!sourcesChecked) await checkAllSources();
    const names = (sources || []).filter(s => s.update && s.updatable).map(s => s.name);
    if (!names.length) { toast.info("Обновлять нечего — всё актуально"); return; }
    const ok = await confirmDialog({
      title: "Обновить всё?",
      description: `Источников к обновлению: ${names.length}. Стратегии Flowseal при обновлении перегенерируются автоматически.`,
      confirmText: "Обновить всё",
    });
    if (!ok) return;
    let done = 0;
    for (const name of names) if (await updateSource(name, true)) done++;
    if (done === names.length) toast.success(`Обновлено источников: ${done}`);
    else toast.warning(`Обновлено ${done} из ${names.length}`, "Остальное — в ошибке в списке ниже");
  }

  // приходит по мере готовности каждого источника во время upstream_check_updates —
  // строка гаснет сразу, не дожидаясь самой медленной сверки
  onPush("srcChecked", s => {
    if (srcBusy.get(s.name) === "check") srcBusy.delete(s.name);
    mergeSource(s);
    render();
  });

  // --- разметка -------------------------------------------------------------------

  function cardSkeleton(title, icon) {
    return `<div class="card"><div class="card-header"><div class="card-title">${ic(icon)}${esc(title)}</div></div>
      <div class="card-content">${skeletonHtml(3)}</div></div>`;
  }

  function opt(cur, v) { return cur === v ? " selected" : ""; }

  // Общее: как программа запускается, закрывается и в чём показывается. Режимы
  // ui/tui/service — инструмент разработчика, остаются в config.json, а не здесь.
  function generalCardHtml() {
    if (!config) return cardSkeleton("Общее", "settings");
    return `
      <div class="card compact">
        <div class="card-header"><div class="card-title">${ic("settings")}Общее</div></div>
        <div class="card-content stack">
          <div class="switch-row">
            <div class="set-row-label"><b>Запускать вместе с Windows</b><span>Сразу свёрнутой в трей, без запроса прав.</span></div>
            ${autostart
              ? switchHtml(!!autostart.enabled, `data-act="autostart"${autostart.supported ? "" : ' data-tip="Не поддерживается на этой системе"'}`,
                  { disabled: !autostart.supported || autostartPending, pending: autostartPending })
              : skeletonHtml(1, 20)}
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Сворачивать в трей при закрытии</b><span>Совсем закрыть — «Выход» в меню значка.</span></div>
            ${switchHtml(config.close_to_tray !== false, 'data-cfg-switch="close_to_tray"', { pending: !!cfgPending.close_to_tray })}
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Запрашивать права администратора</b><span>Без них не работают обход DPI, hosts и смена DNS.</span></div>
            ${switchHtml(config.auto_elevate !== false, 'data-cfg-switch="auto_elevate"', { pending: !!cfgPending.auto_elevate })}
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Окно программы</b><span>Применится после перезапуска.</span></div>
            <select class="select-native set-select" data-cfg="ui_backend"${cfgPending.ui_backend ? " disabled" : ""}>
              ${ENGINES.filter(en => !(en.dev && Store.get("app")?.frozen))
                .map(en => `<option value="${en.id}"${opt(config.ui_backend, en.id)}>${esc(en.title)}</option>`).join("")}
            </select>
          </div>
        </div>
      </div>`;
  }

  function sourceIcon(kind) {
    return { tag: "git-branch", commit: "git-branch", pin: "package", service: "server", python: "terminal" }[kind] || "package";
  }

  function sourceRight(s) {
    const busy = srcBusy.get(s.name);
    if (busy) return badgeHtml(busy === "update" ? "Обновляю…" : "Проверяю…", "info", "loader-circle");
    if (s.error) return `<span data-tip="${esc(s.error)}">${badgeHtml("ошибка", "danger", "circle-alert")}</span>`;
    if (s.kind === "service") return `<span data-tip="${esc(s.note || "")}">${badgeHtml("сервис", "info", "server")}</span>`;
    if (s.latest === undefined) return "";  // не проверяли — рядом и так кнопка «Проверить»
    if (s.kind === "pin") return `<span data-tip="Версия пиннута в коде — обновляется правкой исходников">${badgeHtml("пин в коде", "outline", "lock")}</span>`;
    if (s.update) return `<span data-tip="доступна ${esc(s.latest)}">${badgeHtml("есть обновление", "warning", "arrow-up-right")}</span>`;
    return badgeHtml("актуально", "success", "circle-check");
  }

  function sourceRowHtml(s) {
    const busy = srcBusy.get(s.name);
    const cur = s.version || s.current || "—";
    const updBtn = !s.update || busy ? ""
      : s.updatable
        ? `<button class="btn xs" data-act="update" data-name="${esc(s.name)}">${ic("download")}Обновить</button>`
        : `<button class="btn xs outline" data-act="update" data-name="${esc(s.name)}" disabled
             data-tip="Версия пиннута в коде — обновляется правкой исходников">${ic("download")}Обновить</button>`;
    return `
      <div class="item" data-key="src-${encodeURIComponent(s.name)}">
        <div class="item-media">${ic(sourceIcon(s.kind))}</div>
        <div class="item-body">
          <div class="item-title set-src-name" data-url="${esc(s.repo)}">${esc(s.name)}${ic("external-link")}</div>
          <div class="item-desc mono">${esc(cur)}</div>
        </div>
        <div class="item-actions">
          ${sourceRight(s)}
          <button class="btn xs outline" data-act="check" data-name="${esc(s.name)}"${busy ? " disabled" : ""}>${ic("refresh-cw")}Проверить</button>
          ${updBtn}
        </div>
      </div>`;
  }

  // Компоненты (стратегии Flowseal, zapret2, tg-ws-proxy, бандл winws) обновляются
  // через git — это есть только при запуске из исходников; в сборке карточки нет.
  // Пиннутые версии, Python, шрифты и онлайн-сервис — не то, что пользователь обновляет сам.
  function sourcesCardHtml() {
    if (Store.get("selfupdate")?.frozen) return "";
    const rows = (sources || []).filter(s => s.kind === "tag" || s.kind === "commit");
    return `
      <div class="card compact">
        <div class="card-header">
          <div class="card-title">${ic("package")}Компоненты</div>
          <div class="card-action">
            <button class="btn outline sm" data-act="check-all">${ic("refresh-cw")}Проверить всё</button>
            <button class="btn sm" data-act="update-all">${ic("download")}Обновить всё</button>
          </div>
        </div>
        <div class="card-content set-src-list">
          ${sources
            ? (rows.length ? rows.map(sourceRowHtml).join("") : emptyHtml({ icon: "package", title: "Компонентов нет" }))
            : skeletonHtml(4, 60)}
        </div>
      </div>`;
  }

  // --- обновление самой программы (хаб: selfupdate, см. ui/updater.py) -----------

  let appCheckBusy = false;

  async function checkApp() {
    if (appCheckBusy) return;
    appCheckBusy = true;
    render();
    try {
      const s = await api("selfupdate_check");
      if (s?.error) toast.error("Не удалось проверить обновления", s.error);
      else if (s?.update) toast.info(`Доступна Chimera ${fmtVersion(s.latest)}`);
      else toast.success("Установлена последняя версия");
    } catch (e) {
      toast.error("Не удалось проверить обновления", e.message);
    } finally {
      appCheckBusy = false;
      render();
    }
  }

  async function installApp() {
    const s = Store.get("selfupdate");
    if (!s?.installable) return;
    const ok = await confirmDialog({
      title: `Обновить Chimera до ${fmtVersion(s.latest)}?`,
      description: "Программа скачает новую версию, закроется, обновится и запустится снова. Модули перезапустятся, "
        + "настройки и выбранные списки останутся. Если что-то пойдёт не так, вернётся текущая версия.",
      confirmText: "Обновить",
    });
    if (!ok) return;
    try {
      await api("selfupdate_install");
    } catch (e) {
      toast.error("Не удалось обновить", e.message);
    }
  }

  function appUpdateStatus(s) {
    if (appCheckBusy || s.checking) return { text: "Проверяю…", badge: badgeHtml("проверка", "info", "loader-circle") };
    if (s.stage === "downloading") return { text: `Скачиваю ${fmtVersion(s.latest)} · ${Math.round((s.progress || 0) * 100)}%`, badge: "" };
    if (s.stage === "installing") return { text: "Устанавливаю — программа сейчас перезапустится", badge: badgeHtml("установка", "info", "loader-circle") };
    if (s.error) return { text: s.error, badge: badgeHtml("ошибка", "danger", "circle-alert") };
    if (s.update) return { text: `Доступна ${fmtVersion(s.latest)}`, badge: badgeHtml("есть обновление", "warning", "arrow-up-right") };
    if (s.checked_at) {
      const t = new Date(s.checked_at * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
      return { text: `Последняя версия · проверено в ${t}`, badge: badgeHtml("актуально", "success", "circle-check") };
    }
    return { text: "Ещё не проверялось", badge: "" };
  }

  function appInstallButton(s) {
    if (!s.update || s.stage === "downloading" || s.stage === "installing") return "";
    const label = `${ic("download")}Обновить до ${esc(fmtVersion(s.latest))}`;
    if (s.installable) return `<button class="btn xs" data-act="app-install">${label}</button>`;
    const why = !s.frozen ? "Запуск из исходников — обновляется через git"
      : "У релиза нет контрольной суммы — скачай архив со страницы релиза вручную";
    return `<button class="btn xs outline" disabled data-tip="${esc(why)}">${label}</button>`;
  }

  function appUpdateCardHtml() {
    const s = Store.get("selfupdate");
    if (!s || !config) return cardSkeleton("Обновление Chimera", "download");
    const st = appUpdateStatus(s);
    const busy = appCheckBusy || s.checking || s.stage === "downloading" || s.stage === "installing";
    const channel = config.update_channel || "stable";
    return `
      <div class="card compact">
        <div class="card-header">
          <div class="card-title">${ic("download")}Обновление Chimera</div>
        </div>
        <div class="card-content stack">
          <div class="item" data-key="app-update">
            <div class="item-media"><i data-logo></i></div>
            <div class="item-body">
              <div class="item-title">Chimera ${esc(fmtVersion(s.current))}</div>
              <div class="item-desc"${s.error ? ` data-tip="${esc(s.error)}"` : ""}>${esc(st.text)}${s.update && s.url ? ` · <button type="button" class="btn link" data-url="${esc(s.url)}">что нового</button>` : ""}</div>
              ${s.stage === "downloading" ? `<div class="progress set-app-progress"><i style="transform:scaleX(${s.progress || 0})"></i></div>` : ""}
            </div>
            <div class="item-actions">
              ${st.badge}
              <button class="btn xs outline" data-act="app-check"${busy ? " disabled" : ""}>${ic("refresh-cw")}Проверить</button>
              ${appInstallButton(s)}
            </div>
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Канал обновлений</b><span>Бета — новое раньше, но может быть сыровато.</span></div>
            <select class="select-native set-select" data-cfg="update_channel"${cfgPending.update_channel ? " disabled" : ""}>
              <option value="stable"${opt(channel, "stable")}>Стабильный</option>
              <option value="beta"${opt(channel, "beta")}>Бета</option>
            </select>
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Проверять обновления</b><span>Только покажет новую версию — ставить или нет, решаешь сам.</span></div>
            ${switchHtml(config.update_check !== false, 'data-cfg-switch="update_check"', { pending: !!cfgPending.update_check })}
          </div>
        </div>
      </div>`;
  }

  // Обслуживание: то, что у Flowseal живёт в меню service.bat
  function maintenanceCardHtml() {
    return `
      <div class="card compact">
        <div class="card-header"><div class="card-title">${ic("sparkles")}Обслуживание</div></div>
        <div class="card-content stack">
          <div class="switch-row">
            <div class="set-row-label"><b>Очистить кэш Discord</b><span>Если Discord не подключается после смены стратегии. Закрой его перед очисткой.</span></div>
            <button class="btn outline sm" data-act="discord-cache">${ic("trash-2")}Очистить</button>
          </div>
        </div>
      </div>`;
  }

  async function clearDiscordCache(btn) {
    const ok = await confirmDialog({
      title: "Очистить кэш Discord?",
      description: "Удалятся папки кэша Discord (сам клиент, вход и настройки не пострадают). Discord должен быть закрыт.",
      confirmText: "Очистить",
    });
    if (!ok) return;
    await withBusy(btn, async () => {
      try {
        const r = await api("discord_clear_cache");
        if (!r) return;
        if (!r.cleared?.length) toast.info("Нечего чистить", r.note || "Discord не найден.");
        else toast.success(`Кэш очищен · ${fmtBytes(r.freed_bytes)}`, r.cleared.map(c => c.name).join(", "));
      } catch (e) {
        toast.error("Не удалось очистить", e.message);
      }
    });
  }


  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${generalCardHtml()}
      ${appUpdateCardHtml()}
      ${sourcesCardHtml()}
      ${maintenanceCardHtml()}`);
  }

  // --- события ----------------------------------------------------------------

  function onClick(e) {
    const url = e.target.closest("[data-url]");
    if (url) { api("open_url", url.dataset.url).catch(() => {}); return; }

    const sw = e.target.closest("[data-cfg-switch]");
    if (sw && !sw.disabled) return setConfig(sw.dataset.cfgSwitch, !config[sw.dataset.cfgSwitch]);

    if (e.target.closest('[data-act="autostart"]')) return toggleAutostart();

    const chk = e.target.closest('[data-act="check"]');
    if (chk) return checkOne(chk.dataset.name);

    const upd = e.target.closest('[data-act="update"]');
    if (upd && !upd.disabled) return updateOneConfirm(upd.dataset.name);

    const checkAll = e.target.closest('[data-act="check-all"]');
    if (checkAll) return withBusy(checkAll, checkAllSources);

    const updAll = e.target.closest('[data-act="update-all"]');
    if (updAll) return withBusy(updAll, updateAllConfirm);

    const dc = e.target.closest('[data-act="discord-cache"]');
    if (dc) return clearDiscordCache(dc);

    if (e.target.closest('[data-act="app-check"]')) return checkApp();
    if (e.target.closest('[data-act="app-install"]')) return installApp();
  }

  function onChange(e) {
    const sel = e.target.closest("select[data-cfg]");
    if (sel) setConfig(sel.dataset.cfg, sel.value);
  }

  Pages.define({
    id: "settings", title: "Настройки", icon: "settings", group: "Система",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Настройки</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;
      el.addEventListener("click", onClick);
      el.addEventListener("change", onChange);
      render();
    },
    show(ctx) {
      ctx.on(["app", "selfupdate"], render);
      render();
      refreshConfig();
      refreshAutostart();
      refreshSources();
    },
  });
})();
