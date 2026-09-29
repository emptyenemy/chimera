"use strict";
/* Telegram — локальный MTProto-прокси на базе tg-ws-proxy (Flowseal): Telegram
   Desktop подключается к нему напрямую по host:port, а прокси сам заворачивает
   трафик в WebSocket до дата-центров Telegram. Чинит частичную загрузку без
   внешних серверов. Состояние — ключ хаба `tg` (всегда опрашивается), живая
   статистика — ленивый `tgStats` (только пока эта страница открыта). */

(() => {

  let root;
  let logView = null;
  let secretVisible = false;   // секрет скрыт по умолчанию
  let togglePending = false;   // старт/стоп в полёте — тумблер в целевом положении
  let saveTimer = null;        // debounce автосохранения host/port/secret
  let advancedOpen = false;    // «Продвинутые настройки» свёрнуты по умолчанию
  let advSaveTimer = null;     // debounce автосохранения текстовых продвинутых полей
  let dcDraft = null;          // локальный черновик списка dc_redirects, пока не сохранён
  let cfgDraft = null;         // черновик host/port/secret, пока не долетел до бэкенда
  let advDraft = null;         // черновик доменных списков/fake_tls_domain, пока не сохранён

  // Черновики нужны, потому что render() всегда рисует из Store: без них любой
  // рендер, случившийся раньше debounce (клик по другой кнопке, тик хаба, приход
  // tgStats) стирал бы то, что пользователь только что напечатал, но ещё не
  // долетело до бэкенда.

  // --- сеть / бэкенд ------------------------------------------------------------

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveTimer = null; flushConfig(); }, 500);
  }

  // debounce копит изменения, пока печатают, но уход с поля (клик по другой кнопке,
  // Tab) не должен ждать оставшиеся ~полсекунды
  function flushPendingSave() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; flushConfig(); }
    if (advSaveTimer) { clearTimeout(advSaveTimer); advSaveTimer = null; flushAdvancedText(); }
  }

  async function flushConfig() {
    const st = Store.get("tg");
    if (!st || !cfgDraft) return;
    const host = cfgDraft.host ?? st.host;
    const port = Number(cfgDraft.port ?? st.port);
    const secret = cfgDraft.secret ?? st.secret;
    try {
      await optimistic("tg", { host, port, secret },
        () => api("tg_set_config", host, port, secret, !!st.autostart),
        { errorTitle: "Не удалось сохранить настройки" });
      cfgDraft = null;   // сохранилось — дальше рендерим из tg
    } catch { /* тост уже показан, черновик остаётся, чтобы не потерять правку */ }
    render();
  }

  async function toggleRunning() {
    if (togglePending) return;
    const st = Store.get("tg");
    if (!st) return;
    const target = !st.running;
    togglePending = true;
    render();
    try {
      await optimistic("tg", { running: target }, () => api(target ? "tg_start" : "tg_stop"), {
        errorTitle: target ? "Не удалось запустить прокси" : "Не удалось остановить прокси",
      });
    } catch { /* тост уже показан */ }
    finally { togglePending = false; render(); }
  }

  async function toggleAutostart() {
    const st = Store.get("tg");
    if (!st) return;
    const target = !st.autostart;
    try {
      await optimistic("tg", { autostart: target },
        () => api("tg_set_config", st.host, st.port, st.secret, target),
        { errorTitle: "Не удалось изменить автозапуск" });
    } catch { /* тост уже показан */ }
  }

  async function regenSecret() {
    const ok = await confirmDialog({
      title: "Сгенерировать новый секрет?",
      description: "Прежняя ссылка перестанет работать — устройства, уже подключённые по " +
        "старому секрету, придётся подключить заново.",
      confirmText: "Сгенерировать",
      destructive: true,
    });
    if (!ok) return;
    try {
      await optimistic("tg", {}, () => api("tg_regen_secret"), { errorTitle: "Не удалось сгенерировать секрет" });
      toast.success("Новый секрет сгенерирован");
    } catch { /* тост уже показан */ }
  }

  // --- продвинутые настройки ядра (CF-proxy/worker домены, Fake TLS, dc-ip, ...) ---
  // Ядро читает их только при старте, поэтому запущенный прокси перезапускается сам (Api);
  // сбой перезапуска приезжает в apply_error.

  function dcRows(st) {
    return dcDraft || Object.entries(st?.dc_redirects || {});
  }

  // текущие значения всех строк DC прямо из DOM — источник истины между рендерами
  function liveDcRows() {
    return $$(".tg-dc-row", root).map(row => [
      row.querySelector("[data-dc-num]")?.value ?? "",
      row.querySelector("[data-dc-ip]")?.value ?? "",
    ]);
  }

  function readDcRedirects() {
    const out = {};
    for (const [num, ip] of liveDcRows()) {
      const n = num.trim(), v = ip.trim();
      if (n && v) out[n] = v;
    }
    return out;
  }

  async function saveAdvanced(options) {
    try {
      const res = await api("tg_set_advanced", options);
      if (!res || typeof res !== "object") return false;   // бэкенд не подтвердил — черновик не трогаем
      Store.patch("tg", res);
      if (res.apply_error) toast.error("Настройки сохранены, но прокси не перезапустился", res.apply_error);
      return true;
    } catch (e) {
      toast.error("Не удалось сохранить продвинутые настройки", e.message);
      return false;
    }
  }

  function scheduleAdvancedSave() {
    clearTimeout(advSaveTimer);
    advSaveTimer = setTimeout(() => { advSaveTimer = null; flushAdvancedText(); }, 500);
  }

  async function flushAdvancedText() {
    if (!advDraft && !dcDraft) return;
    const st = Store.get("tg");
    const ok = await saveAdvanced({
      cfproxy_user_domains: advDraft?.cfproxy_user_domains ?? (st?.cfproxy_user_domains || []).join("\n"),
      cfproxy_worker_domains: advDraft?.cfproxy_worker_domains ?? (st?.cfproxy_worker_domains || []).join("\n"),
      fake_tls_domain: advDraft?.fake_tls_domain ?? (st?.fake_tls_domain || ""),
      dc_redirects: readDcRedirects(),
    });
    if (ok) { advDraft = null; dcDraft = null; }   // сохранилось — дальше рендерим из tg
    render();
  }

  async function toggleAdvancedSwitch(key) {
    const st = Store.get("tg");
    if (!st) return;
    const target = !st[key];
    try {
      await optimistic("tg", { [key]: target }, async () => {
        const res = await api("tg_set_advanced", { [key]: target });
        if (res?.apply_error) toast.error("Настройки сохранены, но прокси не перезапустился", res.apply_error);
        return res;
      }, { errorTitle: "Не удалось сохранить" });
    } catch { /* тост уже показан */ }
  }

  function addDcRow() {
    dcDraft = liveDcRows().concat([["", ""]]);
    render();
  }

  function removeDcRow(i) {
    const rows = liveDcRows();
    rows.splice(i, 1);
    dcDraft = rows;
    render();
    scheduleAdvancedSave();
  }

  // --- разметка -------------------------------------------------------------------

  // Шапка — как у стратегий и прокси: статус одной строкой, автозапуск, кнопка; ниже — как подключить
  function heroHtml(st) {
    if (!st) return `<div class="card compact"><div class="card-content">${skeletonHtml(2, 24)}</div></div>`;
    const on = !!st.running;
    return `
      <div class="card compact tg-hero${on ? " is-on" : ""}">
        <div class="card-content tg-status-row">
          <span class="dot ${on ? "on" : ""}"></span>
          <div class="grow tg-status-title">${on ? `Работает · ${esc(st.host)}:${esc(st.port)}` : "Остановлено"}</div>
          <label class="tg-autostart"><span class="muted">Автозапуск</span>${switchHtml(!!st.autostart, 'data-toggle="tg-autostart"')}</label>
          <button type="button" class="btn sm${on ? " destructive" : ""}${togglePending ? " busy" : ""}" data-toggle="tg"${togglePending ? " disabled" : ""}>
            ${togglePending ? ic("loader-circle") : ""}${on ? "Остановить" : "Запустить"}
          </button>
        </div>
        <div class="card-content tg-actions">
          <button class="btn outline sm" data-act="open-link"${st.link ? "" : " disabled"}>${ic("external-link")}Подключить в Telegram</button>
          <button class="btn ghost sm" data-act="copy-link"${st.link ? "" : " disabled"}>${ic("copy")}Скопировать ссылку</button>
          <button class="btn ghost sm" data-act="show-qr"${st.link ? "" : " disabled"}>${ic("qr-code")}QR для телефона</button>
        </div>
        ${st.error ? `<div class="card-content"><div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(st.error)}</div></div></div>` : ""}
      </div>`;
  }

  function configHtml(st) {
    if (!st) return `<div class="card"><div class="card-header"><div class="card-title">${ic("settings")}Настройки подключения</div></div>
      <div class="card-content">${skeletonHtml(4)}</div></div>`;
    const host = cfgDraft?.host ?? st.host;
    const port = cfgDraft?.port ?? st.port;
    const secret = cfgDraft?.secret ?? st.secret;
    return `
      <div class="card compact">
        <div class="card-header"><div class="card-title">${ic("settings")}Подключение</div></div>
        <div class="card-content stack">
          <div class="switch-row">
            <div class="tg-row-label"><b>Адрес</b><span>0.0.0.0 — доступ из локальной сети</span></div>
            <input class="input tg-field" data-f="host" value="${esc(host)}" spellcheck="false">
          </div>
          <div class="switch-row">
            <div class="tg-row-label"><b>Порт</b></div>
            <input class="input tg-field" type="number" min="1" max="65535" data-f="port" value="${esc(port)}">
          </div>
          <div class="switch-row">
            <div class="tg-row-label"><b>Секрет</b></div>
            <div class="input-group tg-secret-group">
              <input class="input mono tg-field" type="${secretVisible ? "text" : "password"}"
                data-f="secret" value="${esc(secret)}" spellcheck="false" autocomplete="off">
              <span class="input-end">
                <button type="button" class="btn ghost sm icon-btn" data-act="toggle-secret"
                  data-tip="${secretVisible ? "Скрыть" : "Показать"}">${ic(secretVisible ? "eye-off" : "eye")}</button>
                <button type="button" class="btn ghost sm icon-btn" data-act="regen-secret"
                  data-tip="Сгенерировать новый">${ic("refresh-cw")}</button>
              </span>
            </div>
          </div>
        </div>
      </div>`;
  }

  // Тело карточки — самая тяжёлая разметка страницы (textarea/строки DC), а открывают
  // её редко: пока она свёрнута, строим только заголовок — нечего диффить на каждый
  // тик хаба (не только render() дороже, ещё и morph гоняет узлы, которые не видны).
  function advancedBodyHtml(st) {
    const rows = dcRows(st);
    const userDomains = advDraft?.cfproxy_user_domains ?? (st.cfproxy_user_domains || []).join("\n");
    const workerDomains = advDraft?.cfproxy_worker_domains ?? (st.cfproxy_worker_domains || []).join("\n");
    const fakeTls = advDraft?.fake_tls_domain ?? (st.fake_tls_domain || "");
    return `
          <div class="card-content stack">
            <div class="switch-row">
              <div class="tg-row-label"><b>Без TLS-маскировки</b><span>Порт 80 для CF-proxy/worker вместо защищённого соединения (--no-secure)</span></div>
              ${switchHtml(!!st.disable_secure, 'data-adv-switch="disable_secure"')}
            </div>
            <div class="switch-row">
              <div class="tg-row-label"><b>Фолбэк через Cloudflare</b><span>Если прямое соединение с Telegram не проходит — заворачивать через CF-домены</span></div>
              ${switchHtml(st.fallback_cfproxy !== false, 'data-adv-switch="fallback_cfproxy"')}
            </div>
            <div class="field">
              <label class="label">Свои домены Cloudflare</label>
              <span class="hint">По одному на строку — вместо автоматического пула CF-proxy.</span>
              <textarea class="textarea mono" data-adv="cfproxy_user_domains" rows="3"
                placeholder="example.com">${esc(userDomains)}</textarea>
            </div>
            <div class="field">
              <label class="label">CF Worker-домены</label>
              <span class="hint">По одному на строку.</span>
              <textarea class="textarea mono" data-adv="cfproxy_worker_domains" rows="3"
                placeholder="worker.example.com">${esc(workerDomains)}</textarea>
            </div>
            <div class="field">
              <label class="label">Домен маскировки (Fake TLS)</label>
              <span class="hint">Если задан — секрет получает вид ee…, трафик маскируется под HTTPS к этому домену.</span>
              <input class="input mono" data-adv="fake_tls_domain" value="${esc(fakeTls)}"
                placeholder="www.example.com" spellcheck="false">
            </div>
            <div class="field">
              <label class="label">Подмена IP дата-центров</label>
              <span class="hint">Номер DC → IP, на который ходить напрямую вместо адреса Telegram.</span>
              <div class="tg-dc-list">
                ${rows.map(([num, ip], i) => `
                  <div class="tg-dc-row" data-key="dc-${i}" data-i="${i}">
                    <input class="input mono tg-dc-num" data-dc-num value="${esc(num)}" placeholder="DC">
                    <input class="input mono tg-dc-ip" data-dc-ip value="${esc(ip)}" placeholder="IP">
                    <button type="button" class="btn ghost sm icon-btn" data-act="dc-remove" data-i="${i}" data-tip="Удалить">${ic("x")}</button>
                  </div>`).join("")}
              </div>
              <button type="button" class="btn outline sm" data-act="dc-add">${ic("plus")}Добавить DC</button>
            </div>
            <div class="switch-row">
              <div class="tg-row-label"><b>PROXY protocol</b><span>Прокси стоит за nginx/haproxy, которые уже отдают PROXY protocol</span></div>
              ${switchHtml(!!st.proxy_protocol, 'data-adv-switch="proxy_protocol"')}
            </div>
            <div class="switch-row">
              <div class="tg-row-label"><b>Тестовые дата-центры</b><span>Принудительно использовать тестовые DC Telegram (--force-test-dc)</span></div>
              ${switchHtml(!!st.force_test_dc, 'data-adv-switch="force_test_dc"')}
            </div>
            ${st.running ? `<div class="alert warning">${ic("triangle-alert")}<div class="alert-desc">Продвинутые настройки применяются только при старте — перезапусти прокси, чтобы их подхватить.</div></div>` : ""}
          </div>`;
  }

  // Выглядит как общий свёрнутый блок (foldHtml), но открытость хранится тут: карточка
  // живёт внутри перерисовываемого morph()-тела, и состояние в DOM оно бы сбросило
  function advancedHtml(st) {
    if (!st) return "";
    return `
      <div class="card fold${advancedOpen ? " open" : ""}">
        <button type="button" class="card-header" data-act="toggle-advanced" aria-expanded="${advancedOpen}">
          <div class="card-title">${ic("sliders-horizontal")}Дополнительно</div>
          <div class="card-action">${ic("chevron-down", "fold-chevron")}</div>
        </button>
        <div class="card-content fold-body"${advancedOpen ? "" : " hidden"}>
          ${advancedOpen ? advancedBodyHtml(st) : ""}
        </div>
      </div>`;
  }

  // статистика есть только у работающего прокси — у остановленного карточки нет вовсе
  function statsHtml(st, stats) {
    if (!st?.running) return "";
    if (!stats) {
      return `<div class="card"><div class="card-header"><div class="card-title">${ic("gauge")}Статистика</div></div>
        <div class="card-content tg-stats">${skeletonHtml(4, 60)}</div></div>`;
    }
    const tiles = [
      ["Активные соединения", fmtNum(stats.active)],
      ["Всего с запуска", fmtNum(stats.total)],
      ["WebSocket", fmtNum(stats.ws)],
      ["TCP-фолбэк", fmtNum(stats.tcp_fallback)],
      ["Через CF", fmtNum(stats.cfproxy)],
      ["Исходящий трафик", esc(stats.up)],
      ["Входящий трафик", esc(stats.down)],
    ];
    return `<div class="card">
      <div class="card-header"><div class="card-title">${ic("gauge")}Статистика</div></div>
      <div class="card-content tg-stats">
        ${tiles.map(([label, value]) => `<div class="tg-stat"><span class="stat-label">${esc(label)}</span><span class="stat-value">${value}</span></div>`).join("")}
      </div>
    </div>`;
  }

  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${heroHtml(Store.get("tg"))}
      ${statsHtml(Store.get("tg"), Store.get("tgStats"))}
      ${configHtml(Store.get("tg"))}
      ${advancedHtml(Store.get("tg"))}`);
  }

  // --- QR для телефона ---------------------------------------------------------
  // Библиотека (vendor/qrcode) подгружается по клику: на странице она нужна редко.
  // Телефон подключается по адресу компьютера в сети, а по умолчанию прокси слушает
  // только 127.0.0.1 — тогда вместо QR предлагаем открыть его для сети.

  let qrLibLoading = null;
  function loadQrLib() {
    if (window.qrcode) return Promise.resolve(window.qrcode);
    if (!qrLibLoading) {
      qrLibLoading = new Promise((ok, fail) => {
        const s = document.createElement("script");
        s.src = "vendor/qrcode/qrcode.js";
        s.onload = () => (window.qrcode ? ok(window.qrcode) : fail(new Error("Библиотека QR не загрузилась")));
        s.onerror = () => { qrLibLoading = null; fail(new Error("Не удалось загрузить библиотеку QR")); };
        document.head.appendChild(s);
      });
    }
    return qrLibLoading;
  }

  const isLoopbackHost = h => ["", "127.0.0.1", "localhost", "::1"].includes(String(h ?? "").trim().toLowerCase());

  // Белый фон и чёрные модули в любой теме: на тёмном фоне камера код не считает
  function qrSvg(text) {
    const qr = window.qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount(), quiet = 4, size = n + quiet * 2;
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + quiet} ${r + quiet}h1v1h-1z`;
    return `<svg class="tg-qr-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="QR-код ссылки Telegram-прокси" shape-rendering="crispEdges">
      <rect width="${size}" height="${size}" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  }

  function qrBodyHtml(st) {
    if (!st?.link) return `<p class="muted">Ссылка ещё не готова.</p>`;
    if (isLoopbackHost(st.host)) {
      return `
        <div class="tg-qr-note">
          <p>Сейчас прокси слушает только этот компьютер (${esc(st.host)}), поэтому телефон к нему не подключится.</p>
          <p class="muted">Откройте прокси для устройств в вашей сети Wi-Fi: он перезапустится сам. Подключиться сможет любой, кто знает секрет из ссылки, а Windows может спросить разрешение в брандмауэре.</p>
          <button class="btn" data-qr-lan="open">Открыть для устройств в сети</button>
        </div>`;
    }
    return `
      <div class="tg-qr">
        <div class="tg-qr-code">${qrSvg(st.link)}</div>
        <p class="muted">Наведите камеру телефона на QR-код и откройте ссылку в Telegram. Телефон должен быть в той же сети Wi-Fi, что и этот компьютер.</p>
        ${st.running ? "" : `<div class="alert warning">${ic("triangle-alert")}<div class="alert-desc">Прокси остановлен. Запустите его, иначе телефон не подключится.</div></div>`}
        <button class="btn ghost sm" data-qr-lan="close">Вернуть: только этот компьютер</button>
      </div>`;
  }

  async function openQrDialog() {
    if (!Store.get("tg")?.link) return;
    try { await loadQrLib(); }
    catch (err) { toast.error("QR недоступен", err.message); return; }

    let off = () => {};
    openDialog({
      title: "Подключить телефон",
      description: "Telegram-прокси на этом компьютере",
      body: `<div class="tg-qr-host" data-qr-body></div>`,
      onClose: () => off(),
      onMount: h => {
        const host = h.el.querySelector("[data-qr-body]");
        const paint = () => { host.innerHTML = qrBodyHtml(Store.get("tg")); if (window.icons) window.icons(host); };
        paint();
        off = Store.on("tg", paint);
        h.el.addEventListener("click", ev => {
          const btn = ev.target.closest("[data-qr-lan]");
          if (!btn || btn.disabled) return;
          const st = Store.get("tg");
          const toHost = btn.dataset.qrLan === "open" ? "0.0.0.0" : "127.0.0.1";
          // без оптимистичной правки: ссылку с адресом компьютера в сети считает
          // бэкенд, а до его ответа QR показывал бы старую (127.0.0.1)
          withBusy(btn, () => optimistic("tg", null,
            () => api("tg_set_config", toHost, Number(st.port), st.secret, !!st.autostart),
            { errorTitle: "Не удалось изменить доступ" }).catch(() => {}));
        });
      },
    });
  }

  // --- события ----------------------------------------------------------------

  function onClick(e) {
    const url = e.target.closest("[data-url]");
    if (url) { api("open_url", url.dataset.url).catch(() => {}); return; }

    if (e.target.closest('[data-toggle="tg"]')) return toggleRunning();
    if (e.target.closest('[data-toggle="tg-autostart"]')) return toggleAutostart();

    const openLink = e.target.closest('[data-act="open-link"]');
    if (openLink && !openLink.disabled) return withBusy(openLink, () => api("tg_open_link").catch(e2 => toast.error("Не удалось открыть", e2.message)));

    const copyLink = e.target.closest('[data-act="copy-link"]');
    if (copyLink && !copyLink.disabled) {
      const st = Store.get("tg");
      if (st?.link) copyText(st.link);
      return;
    }

    const showQr = e.target.closest('[data-act="show-qr"]');
    if (showQr && !showQr.disabled) return openQrDialog();

    if (e.target.closest('[data-act="toggle-secret"]')) { secretVisible = !secretVisible; render(); return; }
    if (e.target.closest('[data-act="regen-secret"]')) return regenSecret();

    if (e.target.closest('[data-act="toggle-advanced"]')) { advancedOpen = !advancedOpen; render(); return; }

    const advSwitch = e.target.closest("[data-adv-switch]");
    if (advSwitch) return toggleAdvancedSwitch(advSwitch.dataset.advSwitch);

    if (e.target.closest('[data-act="dc-add"]')) return addDcRow();

    const dcRemove = e.target.closest('[data-act="dc-remove"]');
    if (dcRemove) return removeDcRow(Number(dcRemove.dataset.i));
  }

  function onInput(e) {
    const f = e.target.closest(".tg-field[data-f]");
    if (f) { cfgDraft = { ...(cfgDraft || {}), [f.dataset.f]: f.value }; return scheduleSave(); }

    const adv = e.target.closest("[data-adv]");
    if (adv) { advDraft = { ...(advDraft || {}), [adv.dataset.adv]: adv.value }; return scheduleAdvancedSave(); }

    if (e.target.closest(".tg-dc-row")) {
      dcDraft = liveDcRows();
      scheduleAdvancedSave();
    }
  }

  function onKeydown(e) {
    if (e.key !== "Enter") return;
    if (e.target.closest(".tg-field[data-f]")) {
      e.target.blur();   // сработает focusout -> flushPendingSave
      return;
    }
    // однострочные продвинутые поля — Enter коммитит сразу; textarea (списки доменов)
    // Enter оставляет переносом строки
    if (e.target.matches('input[data-adv]') || e.target.closest(".tg-dc-row")) {
      e.target.blur();
    }
  }

  // уход с поля (Tab, клик по другой кнопке) не должен ждать оставшийся debounce
  function onFocusOut() {
    flushPendingSave();
  }

  Pages.define({
    id: "telegram", title: "Telegram", icon: "send", group: "Обход",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Telegram-прокси</h1>
          </div>
        </div>
        <div class="stack">
          <div class="stack" data-slot="body"></div>
          ${foldHtml("terminal", "Логи", '<div id="tg-log" class="log"></div>')}
        </div>`;
      el.addEventListener("click", onClick);
      el.addEventListener("input", onInput);
      el.addEventListener("keydown", onKeydown);
      el.addEventListener("focusout", onFocusOut);
      render();
      logView = new LogView($("#tg-log", root), "tg_log");
    },
    show(ctx) {
      ctx.on(["tg", "tgStats"], render);
      ctx.watch(["tgStats"]);
      logView.attach(ctx);
      render();
    },
  });
})();
