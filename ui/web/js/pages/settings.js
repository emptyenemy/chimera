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


  // Обмен конфигом: поделиться частью настроек и применить чужой конфиг с предпросмотром.
  // Разделы независимы; настройки обхода DPI по умолчанию выключены — у других провайдер другой.
  const SHARE_SECTIONS = [
    { id: "lists", title: "Списки доменов", desc: "Только те, на которые ссылаются выбранные разделы", on: true },
    { id: "proxy", title: "Прокси", desc: "Режим, списки, приложения. Ссылка на сервер не входит", on: true },
    { id: "hosts", title: "Hosts", desc: "Привязки списков и свои провайдеры", on: true },
    { id: "dns", title: "DNS-провайдеры", desc: "Свои провайдеры", on: true },
    { id: "telegram", title: "Telegram-прокси", desc: "Порт и продвинутые опции. Секрет не входит", on: true },
    { id: "winws", title: "Обход DPI", desc: "Зависит от провайдера: у тех, у кого другая сеть, может навредить", on: false, warn: true },
  ];

  function shareCardHtml() {
    return `
      <div class="card compact">
        <div class="card-header"><div class="card-title">${ic("send")}Обмен конфигом</div></div>
        <div class="card-content stack">
          <div class="switch-row">
            <div class="set-row-label"><b>Поделиться настройками</b><span>Выберите разделы и скопируйте конфиг. Ссылка на ваш прокси-сервер и секреты в него не попадают.</span></div>
            <button class="btn outline sm" data-act="share-export">${ic("upload")}Поделиться</button>
          </div>
          <div class="switch-row">
            <div class="set-row-label"><b>Применить чужой конфиг</b><span>Перед применением покажем, что изменится. Перед изменением файлы копируются в data/backups.</span></div>
            <button class="btn outline sm" data-act="share-import">${ic("download")}Применить…</button>
          </div>
        </div>
      </div>`;
  }

  function openShareExport() {
    const rows = SHARE_SECTIONS.map(s => `
      <label class="check-row share-row">
        <input type="checkbox" class="checkbox" value="${s.id}" ${s.on ? "checked" : ""}>
        <span><b>${esc(s.title)}</b>${s.warn ? ` ${badgeHtml("зависит от провайдера", "outline")}` : ""}<br><span class="muted">${esc(s.desc)}</span></span>
      </label>`).join("");
    openDialog({
      title: "Поделиться настройками",
      description: "Какие разделы включить в конфиг.",
      body: `<div class="stack-sm" data-share-body>${rows}</div>`,
      footer: `<button class="btn outline" data-close>Закрыть</button><button class="btn" data-share-build>Собрать конфиг</button>`,
      onMount: h => {
        const body = h.el.querySelector("[data-share-body]");
        const build = h.el.querySelector("[data-share-build]");
        build.addEventListener("click", () => withBusy(build, async () => {
          const chosen = [...body.querySelectorAll("input:checked")].map(i => i.value);
          if (!chosen.length) return toast.warning("Выберите хотя бы один раздел");
          try {
            const text = await api("config_export", chosen);
            body.innerHTML = `
              <p class="muted">Скопируйте текст и отправьте его. Получатель вставит его в «Применить чужой конфиг».</p>
              <textarea class="textarea mono share-text" readonly spellcheck="false">${esc(text)}</textarea>`;
            build.textContent = "Скопировать";
            build.onclick = () => copyText(text);
            const ta = body.querySelector("textarea");
            ta.focus(); ta.select();
          } catch (e) {
            toast.error("Не удалось собрать конфиг", e.message);
          }
        }));
      },
    });
  }

  function sharePreviewHtml(pv) {
    if (!pv.ok) {
      return `<div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(pv.error || "Конфиг не подходит.")}</div></div>`;
    }
    const sections = pv.sections.map(s => `
      <div class="share-sec" data-sec="${esc(s.id)}">
        <label class="check-row">
          <input type="checkbox" class="checkbox" value="${esc(s.id)}" ${s.provider_dependent ? "" : "checked"}>
          <b>${esc(s.title)}</b>${s.provider_dependent ? ` ${badgeHtml("зависит от провайдера", "outline")}` : ""}
        </label>
        <ul class="share-list">
          ${s.changes.map(c => `<li>${esc(c)}</li>`).join("")}
          ${s.confirm.map(c => `<li class="share-warn">${ic("triangle-alert")}${esc(c)}</li>`).join("")}
          ${s.skipped.map(c => `<li class="muted">Пропущено: ${esc(c)}</li>`).join("")}
          ${!s.changes.length && !s.confirm.length && !s.skipped.length ? `<li class="muted">Без изменений</li>` : ""}
        </ul>
      </div>`).join("");
    const notes = [];
    if (pv.unknown_sections.length) notes.push(`Не поддерживается вашей версией: ${pv.unknown_sections.join(", ")}`);
    const uf = Object.entries(pv.unknown_fields || {}).map(([k, v]) => `${k}: ${v.join(", ")}`);
    if (uf.length) notes.push(`Неизвестные поля не применятся: ${uf.join("; ")}`);
    if (pv.invalid.length) notes.push(`Отброшено как некорректное: ${pv.invalid.length}`);
    return `
      ${sections}
      ${notes.map(n => `<p class="muted">${esc(n)}</p>`).join("")}
      ${pv.needs_confirm ? `<label class="check-row share-confirm"><input type="checkbox" class="checkbox" data-share-confirm>
        <span>Я доверяю автору конфига: разрешить чужие серверы DNS и hosts и домены-ретрансляторы Telegram (они подменяют ответы DNS и пропускают через себя трафик)</span></label>` : ""}`;
  }

  function openShareImport() {
    openDialog({
      title: "Применить чужой конфиг",
      description: "Вставьте текст конфига или откройте файл. Сначала покажем, что изменится.",
      wide: true,
      body: `
        <div class="stack-sm">
          <textarea class="textarea mono share-text" data-share-text placeholder="Вставьте конфиг сюда" spellcheck="false"></textarea>
          <div class="share-actions">
            <button class="btn outline sm" data-share-open>${ic("folder-open")}Открыть файл…</button>
            <input type="file" accept=".chimera,.json,application/json,text/plain" hidden data-share-file>
            <button class="btn outline sm" data-share-check>${ic("scan-search")}Проверить</button>
          </div>
          <div class="stack-sm" data-share-preview></div>
        </div>`,
      footer: `<button class="btn outline" data-close>Закрыть</button><button class="btn" data-share-apply disabled>Применить</button>`,
      onMount: h => {
        const el = h.el;
        const text = el.querySelector("[data-share-text]");
        const box = el.querySelector("[data-share-preview]");
        const apply = el.querySelector("[data-share-apply]");
        const check = el.querySelector("[data-share-check]");
        const refreshApply = () => {
          const any = [...box.querySelectorAll(".share-sec input:checked")].length > 0;
          const needConfirm = box.querySelector("[data-share-confirm]");
          apply.disabled = !any;
          apply.dataset.needConfirm = needConfirm ? "1" : "";
        };
        const runCheck = () => withBusy(check, async () => {
          apply.disabled = true;
          try {
            const pv = await api("config_import_preview", text.value);
            box.innerHTML = sharePreviewHtml(pv);
            if (window.icons) window.icons(box);
            if (pv.ok) refreshApply();
          } catch (e) {
            box.innerHTML = `<div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(e.message)}</div></div>`;
          }
        });
        check.addEventListener("click", runCheck);
        box.addEventListener("change", refreshApply);
        const file = el.querySelector("[data-share-file]");
        el.querySelector("[data-share-open]").addEventListener("click", () => file.click());
        file.addEventListener("change", () => {
          const f = file.files?.[0];
          if (!f) return;
          const r = new FileReader();
          r.onload = () => { text.value = String(r.result || ""); runCheck(); };
          r.readAsText(f);
        });
        apply.addEventListener("click", () => withBusy(apply, async () => {
          const chosen = [...box.querySelectorAll(".share-sec input:checked")].map(i => i.value);
          const confirmed = !!box.querySelector("[data-share-confirm]:checked");
          try {
            const res = await api("config_import_apply", text.value, chosen, confirmed);
            const skipped = Object.values(res.skipped || {}).flat().length;
            if (res.errors?.length) toast.warning("Применено с ошибками", res.errors.join("\n"));
            else toast.success("Конфиг применён", skipped ? `Пропущено: ${skipped}` : (res.backup ? "Прежние файлы сохранены в data/backups." : ""));
            h.close();
          } catch (e) {
            toast.error("Не удалось применить", e.message);
          }
        }));
      },
    });
  }

  // Диагностика: проверки «почему обход может не работать» и отчёт для issue
  let doctor = null;   // результат последнего запуска: { checks, summary }

  const DOCTOR_ICONS = { ok: "circle-check", warn: "triangle-alert", fail: "circle-x" };

  function doctorCardHtml() {
    const s = doctor?.summary;
    const rows = (doctor?.checks || []).map(c => `
      <div class="doc-row" data-key="doc-${esc(c.id)}">
        <span class="doc-ico ${esc(c.status)}">${ic(DOCTOR_ICONS[c.status] || "circle-help")}</span>
        <div class="grow">
          <div class="doc-title">${esc(c.title)}</div>
          <div class="doc-msg">${esc(c.message)}</div>
          ${c.status !== "ok" && c.hint ? `<div class="doc-hint">${esc(c.hint)}</div>` : ""}
        </div>
      </div>`).join("");
    return `
      <div class="card compact">
        <div class="card-header"><div class="card-title">${ic("activity")}Диагностика</div></div>
        <div class="card-content stack">
          <div class="switch-row">
            <div class="set-row-label"><b>Проверить, почему обход может не работать</b><span>${
              s ? `Проверок: ${s.ok + s.warn + s.fail}, замечаний: ${s.warn}, проблем: ${s.fail}. Ничего не меняется.`
                : "Права, драйвер, порты, чужие процессы, прокси в системе. Ничего не меняется."}</span></div>
            <div class="row gap-2">
              <button class="btn outline sm" data-act="doctor-copy"${doctor ? "" : " disabled"}>${ic("clipboard-copy")}Скопировать отчёт</button>
              <button class="btn outline sm" data-act="doctor-run">${ic("activity")}Проверить</button>
            </div>
          </div>
          ${rows ? `<div class="doc-list">${rows}</div>` : ""}
        </div>
      </div>`;
  }

  async function runDoctor(btn) {
    await withBusy(btn, async () => {
      try {
        doctor = await api("doctor_run");
      } catch (e) {
        toast.error("Диагностика не удалась", e.message);
      }
      render();
    });
  }

  async function copyDoctorReport(btn) {
    await withBusy(btn, async () => {
      try {
        copyText(await api("doctor_report"));
      } catch (e) {
        toast.error("Не удалось собрать отчёт", e.message);
      }
    });
  }

  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${generalCardHtml()}
      ${appUpdateCardHtml()}
      ${sourcesCardHtml()}
      ${shareCardHtml()}
      ${doctorCardHtml()}
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

    if (e.target.closest('[data-act="share-export"]')) return openShareExport();
    if (e.target.closest('[data-act="share-import"]')) return openShareImport();

    const dr = e.target.closest('[data-act="doctor-run"]');
    if (dr) return runDoctor(dr);
    const dcp = e.target.closest('[data-act="doctor-copy"]');
    if (dcp && !dcp.disabled) return copyDoctorReport(dcp);

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
