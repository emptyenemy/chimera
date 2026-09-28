"use strict";
/* Списки доменов и IP (lists/*.txt) — общий источник для прокси, hosts и запрета DPI.
   Двухпанельный вид: слева файлы с метками транспорта и поиском, справа редактор
   с автосохранением. Список — до нескольких тысяч строк, поэтому тяжёлое (счётчик,
   запрос на сохранение) висит на debounce, а не на каждом нажатии клавиши. */

(() => {
  let root, body;
  let lists = null;          // кэш lists_all — переживает уход со страницы
  let query = "";
  let searchTimer = null;

  let current = null;        // имя открытого списка
  let editorText = "";
  let editorLoading = false;
  let editorCount = null;
  let status = "";           // "" | saving | saved | error
  let errorMsg = "";
  let dirty = false;
  let saveTimer = null;

  const TRANSPORTS = [
    { key: "proxy", icon: "globe", label: "Прокси" },
    { key: "winws", icon: "shield", label: "Запрет" },
    { key: "hosts", icon: "server", label: "Hosts" },
  ];

  // --- рендер --------------------------------------------------------------

  function filteredLists() {
    const q = query.trim().toLowerCase();
    return q ? lists.filter(f => f.name.toLowerCase().includes(q)) : lists;
  }

  function fileItemHtml(f) {
    const badges = TRANSPORTS.filter(t => f[t.key])
      .map(t => `<span class="lst-badge lst-badge-${t.key}" data-tip="Идёт через: ${esc(t.label.toLowerCase())}">${ic(t.icon)}</span>`)
      .join("");
    return `
      <div class="item interactive lst-item" data-key="lst-${esc(f.name)}" data-name="${esc(f.name)}" aria-selected="${f.name === current}">
        <span class="grow lst-item-name">${esc(f.name)}</span>
        ${badges ? `<span class="cluster lst-badges">${badges}</span>` : ""}
        <span class="badge secondary num">${fmtNum(f.count)}</span>
      </div>`;
  }

  function sideHtml() {
    if (lists == null) return skeletonHtml(7, 40);
    if (!lists.length) return emptyHtml({ icon: "list", title: "Списков нет", desc: "Создай первый список доменов или IP кнопкой сверху." });
    const items = filteredLists();
    if (!items.length) return emptyHtml({ icon: "search", title: "Ничего не нашлось", desc: `По запросу «${query.trim()}» списков нет.` });
    return `<div class="stack-sm">${items.map(fileItemHtml).join("")}</div>`;
  }

  function statusHtml() {
    if (status === "saving") return `<span class="badge outline">${ic("loader-circle", "spin")}Сохраняю…</span>`;
    if (status === "saved") return `<span class="badge success">${ic("circle-check")}Сохранено</span>`;
    if (status === "error") return `<span class="badge danger">${ic("circle-alert")}Ошибка</span>`;
    return "";
  }

  function countText() {
    return editorCount != null ? `${fmtNum(editorCount)} ${plural(editorCount, "запись", "записи", "записей")}` : "";
  }

  function editorHtml() {
    if (!current) {
      return `
        <div class="card lst-editor-card">
          <div class="card-content grow">
            ${emptyHtml({ icon: "file-text", title: "Список не выбран", desc: "Выбери список слева или создай новый — здесь появится редактор." })}
          </div>
        </div>`;
    }
    return `
      <div class="card lst-editor-card">
        <div class="card-header">
          <div class="card-title mono">${esc(current)}.txt</div>
          <div class="card-action cluster">
            <span data-key="lst-status-slot">${statusHtml()}</span>
            <span class="muted mono" data-key="lst-count-slot">${countText()}</span>
          </div>
        </div>
        <div class="card-content grow lst-editor-wrap">
          ${editorLoading ? skeletonHtml(12, 18)
            : `<textarea class="textarea mono lst-editor" data-key="lst-textarea" spellcheck="false"
                 placeholder="domain.com&#10;sub.domain.com&#10;# комментарий">${esc(editorText)}</textarea>`}
        </div>
        ${errorMsg ? `<div class="card-content">${errorAlert(errorMsg)}</div>` : ""}
      </div>`;
  }

  function errorAlert(msg) {
    return `<div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(msg)}</div></div>`;
  }

  function render() {
    morph(body, `
      <div class="lst-layout">
        <div class="card lst-side">
          <div class="card-header">
            <div class="card-title">${ic("list")}Списки</div>
            <div class="card-action"><button class="btn sm icon-btn" data-new data-tip="Новый список">${ic("plus")}</button></div>
          </div>
          <div class="card-content">
            <div class="input-group">${ic("search")}<input class="input" data-search placeholder="Поиск по спискам…" value="${esc(query)}"></div>
          </div>
          <div class="card-content lst-side-scroll">${sideHtml()}</div>
        </div>
        ${editorHtml()}
      </div>`);
  }

  // мелкие точечные обновления — без пересборки всей страницы на каждое нажатие
  function updateStatusUI() {
    const slot = body?.querySelector('[data-key="lst-status-slot"]');
    if (slot) slot.innerHTML = statusHtml();
    const cnt = body?.querySelector('[data-key="lst-count-slot"]');
    if (cnt) cnt.textContent = countText();
  }
  function setStatus(s) { status = s; updateStatusUI(); }

  function updateSideCount(name, count) {
    const el = body?.querySelector(`.lst-item[data-name="${CSS.escape(name)}"] .badge`);
    if (el) el.textContent = fmtNum(count);
  }

  // --- данные ----------------------------------------------------------------

  async function loadLists() {
    render();  // кэш (или скелетон в первый раз) сразу, обновление — в фоне
    try {
      lists = await api("lists_all");
    } catch (e) {
      lists = lists || [];
      toast.error("Не удалось загрузить списки", e.message);
    }
    render();
  }

  async function openList(name) {
    if (current === name) return;
    await flushSave();
    current = name;
    editorLoading = true;
    editorText = "";
    errorMsg = "";
    status = "";
    editorCount = lists?.find(f => f.name === name)?.count ?? null;
    render();
    try {
      const text = await api("lists_read", name);
      if (current !== name) return;  // успели переключиться, пока читали
      editorText = text;
    } catch (e) {
      if (current !== name) return;
      errorMsg = e.message;
      toast.error("Не удалось открыть список", e.message);
    } finally {
      if (current === name) { editorLoading = false; render(); }
    }
  }

  function closeEditor() {
    current = null;
    editorText = ""; editorCount = null; errorMsg = ""; status = ""; editorLoading = false;
    dirty = false;
    clearTimeout(saveTimer); saveTimer = null;
    render();
  }

  async function flushSave() {
    clearTimeout(saveTimer); saveTimer = null;
    if (!dirty || !current) return;
    const name = current;
    const ta = body?.querySelector(".lst-editor");
    if (!ta) return;
    const content = ta.value;
    dirty = false;
    try {
      const info = await api("lists_save", name, content);
      if (current === name) {
        editorCount = info?.count ?? editorCount;
        errorMsg = "";
        setStatus("saved");
      }
      const item = lists?.find(f => f.name === name);
      if (item && info) { item.count = info.count; updateSideCount(name, info.count); }
      // список сохранён и применяется сам; если какой-то модуль не смог — говорим, какой
      for (const err of info?.apply_errors || []) toast.error(`Список сохранён, но не применён: ${moduleTitle(err.module)}`, err.error);
    } catch (e) {
      dirty = true;  // не терять правки, если сохранить не вышло
      if (current === name) { errorMsg = e.message; setStatus("error"); }
    }
  }

  const MODULE_TITLES = { winws: "стратегии", proxy: "прокси", hosts: "hosts" };
  const moduleTitle = m => MODULE_TITLES[m] || m;

  async function createList() {
    const name = await promptDialog({ title: "Новый список", label: "Имя файла (без .txt)", placeholder: "например, discord" });
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await api("lists_create", trimmed);
      await loadLists();
      openList(trimmed);
    } catch (e) {
      toast.error("Не удалось создать список", e.message);
    }
  }

  async function renameList(name) {
    const next = await promptDialog({ title: "Переименовать список", label: "Новое имя (без .txt)", value: name });
    if (!next || next === name) return;
    if (!/^[A-Za-z0-9._-]+$/.test(next)) {
      toast.error("Некорректное имя", "Только латиница, цифры, точка, дефис и подчёркивание.");
      return;
    }
    if (lists?.some(f => f.name === next)) {
      toast.error("Не удалось переименовать", `Список «${next}» уже существует.`);
      return;
    }
    try {
      const info = await api("lists_rename", name, next);
      toast.success(`${name} → ${info.name}`);
      if (current === name) current = info.name;
      await loadLists();
    } catch (e) {
      toast.error("Не удалось переименовать", e.message);
    }
  }

  async function deleteList(name) {
    const ok = await confirmDialog({
      title: "Удалить список?",
      description: `Список «${name}» будет удалён без возможности восстановления.`,
      confirmText: "Удалить",
      destructive: true,
    });
    if (!ok) return;
    try {
      const res = await api("lists_delete", name);
      toast.success(`Список ${name} удалён`);
      for (const err of res?.apply_errors || []) toast.error(`Не удалось обновить: ${moduleTitle(err.module)}`, err.error);
      if (current === name) closeEditor();
      await loadLists();
    } catch (e) {
      toast.error("Не удалось удалить список", e.message);
    }
  }

  async function toggleTransport(name, key) {
    const item = lists?.find(f => f.name === name);
    if (!item) return;
    const label = key === "proxy" ? "прокси" : "запрет";
    const makeActive = !item[key];
    item[key] = makeActive;  // оптимистично: бейдж меняется сразу, не ждём перезапуска движка
    render();
    toast.info(`${name}: ${label} ${makeActive ? "включён" : "выключен"}.`);
    const next = (lists || []).filter(f => f[key]).map(f => f.name);
    const method = key === "proxy" ? "proxy_set_lists" : "winws_set_lists";
    try {
      await api(method, next);
    } catch (e) {
      item[key] = !makeActive;
      render();
      toast.error(`Не удалось включить ${label}`, e.message);
    }
  }

  // --- события -----------------------------------------------------------------

  function onClick(e) {
    if (e.target.closest("[data-new]")) return createList();
    if (e.target.closest('[data-act="record"]')) return openRecordDialog();
    const item = e.target.closest(".lst-item[data-name]");
    if (item) openList(item.dataset.name);
  }

  function onInput(e) {
    if (e.target.matches("[data-search]")) {
      query = e.target.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(render, 120);
      return;
    }
    if (e.target.matches(".lst-editor")) {
      // держим editorText в ногу с textarea: иначе несвязанный render() (поиск,
      // переключение транспорта у другого списка) морфнёт текст обратно, стерев правки
      editorText = e.target.value;
      dirty = true;
      setStatus("saving");
      clearTimeout(saveTimer);
      saveTimer = setTimeout(flushSave, 500);
    }
  }

  function onContext(e) {
    const row = e.target.closest(".lst-item[data-name]");
    if (!row) return;
    e.preventDefault();
    const name = row.dataset.name;
    const f = lists?.find(x => x.name === name);
    if (!f) return;
    openMenu(e.clientX, e.clientY, [
      { label: `Прокси (VPN)${f.proxy ? " — вкл" : ""}`, icon: "globe", onSelect: () => toggleTransport(name, "proxy") },
      { label: `Запрет (winws)${f.winws ? " — вкл" : ""}`, icon: "shield", onSelect: () => toggleTransport(name, "winws") },
      { label: "Hosts — привязка во вкладке Hosts", icon: "server", disabled: true },
      "sep",
      { label: "Переименовать", icon: "pencil", onSelect: () => renameList(name) },
      { label: "Удалить", icon: "trash-2", destructive: true, onSelect: () => deleteList(name) },
    ]);
  }

  // --- запись доменов сайта -------------------------------------------------
  // Открываешь сайт, пока идёт запись, — Chimera показывает, какие домены ему понадобились
  // (разница кэша DNS Windows), и добавляет выбранные в список одним нажатием.

  function openRecordDialog() {
    let timer = null, seconds = 0;
    const stopTimer = () => { clearInterval(timer); timer = null; };
    openDialog({
      title: "Записать домены сайта",
      description: "Какие домены нужны сайту (картинки, скрипты, API), чтобы не искать их вручную.",
      body: `<div class="stack-sm" data-rec-body></div>`,
      onClose: stopTimer,
      onMount: h => {
        const box = h.el.querySelector("[data-rec-body]");
        const paint = html => { box.innerHTML = html; if (window.icons) window.icons(box); };
        const intro = () => paint(`
          <p>Нажмите «Начать», откройте в браузере сайт, который не открывается, дождитесь загрузки и вернитесь сюда нажать «Стоп».</p>
          <p class="muted">Перед записью сбросим кэш DNS (это безопасно). Видны только домены, которые прошли через DNS Windows: если в браузере включён защищённый DNS (DNS через HTTPS), часть доменов не покажется. Отключите его на время записи.</p>
          <div class="dialog-footer"><button class="btn outline" data-close>Закрыть</button><button class="btn" data-rec-start>${ic("play")}Начать</button></div>`);
        const result = res => {
          const groups = res.domains || [];
          if (!groups.length) {
            return paint(`
              <p>Новых доменов не появилось.</p>
              <p class="muted">Проверьте, что сайт открывался во время записи. Если в браузере включён защищённый DNS, отключите его на время записи.${res.flushed ? "" : " Кэш DNS не сбросили (нет прав администратора): домены, уже бывшие в нём, не показываются."}</p>
              <div class="dialog-footer"><button class="btn outline" data-close>Закрыть</button><button class="btn" data-rec-start>${ic("play")}Повторить</button></div>`);
          }
          const rows = groups.map(g => `
            <label class="check-row rec-row">
              <input type="checkbox" class="checkbox" value="${esc(g.domain)}" ${g.tracker ? "" : "checked"}>
              <span><b>${esc(g.domain)}</b>${g.tracker ? ` ${badgeHtml("возможно трекер", "outline")}` : ""}
                <br><span class="muted">${esc(g.hosts.slice(0, 3).join(", "))}${g.hosts.length > 3 ? ` и ещё ${g.hosts.length - 3}` : ""}</span></span>
            </label>`).join("");
          const opts = (lists || []).map(f => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join("");
          paint(`
            <p class="muted">Записано за ${res.seconds} с. Отметьте домены, которые нужно добавить.</p>
            <div class="stack-sm rec-list">${rows}</div>
            <div class="field"><label class="label">Добавить в список</label><select class="select-native" data-rec-target>${opts}</select></div>
            <div class="dialog-footer"><button class="btn outline" data-close>Закрыть</button><button class="btn" data-rec-add>Добавить</button></div>`);
        };
        h.el.addEventListener("click", async e => {
          const start = e.target.closest("[data-rec-start]");
          if (start) {
            return withBusy(start, async () => {
              try {
                await api("dns_record_start");
              } catch (err) { return toast.error("Не удалось начать запись", err.message); }
              seconds = 0;
              paint(`
                <p><b>Идёт запись…</b> Откройте сайт в браузере, дождитесь загрузки и вернитесь сюда.</p>
                <p class="muted">Прошло <span data-rec-sec>0</span> с</p>
                <div class="dialog-footer"><button class="btn" data-rec-stop>${ic("square")}Стоп</button></div>`);
              timer = setInterval(() => { seconds++; const el = box.querySelector("[data-rec-sec]"); if (el) el.textContent = seconds; }, 1000);
            });
          }
          const stop = e.target.closest("[data-rec-stop]");
          if (stop) {
            stopTimer();
            return withBusy(stop, async () => {
              try { result(await api("dns_record_stop")); }
              catch (err) { toast.error("Не удалось остановить запись", err.message); intro(); }
            });
          }
          const add = e.target.closest("[data-rec-add]");
          if (add) {
            const chosen = [...box.querySelectorAll(".rec-list input:checked")].map(i => i.value);
            const target = box.querySelector("[data-rec-target]")?.value;
            if (!chosen.length) return toast.warning("Отметьте хотя бы один домен");
            if (!target) return toast.warning("Нет списка, куда добавлять", "Сначала создайте список.");
            return withBusy(add, async () => {
              try {
                const text = await api("lists_read", target);
                const have = new Set(text.split(/\r?\n/).map(s => s.trim()));
                const fresh = chosen.filter(d => !have.has(d));
                if (!fresh.length) { toast.info("Всё уже есть в списке"); return h.close(); }
                const info = await api("lists_save", target, text.replace(/\s*$/, "") + "\n" + fresh.join("\n") + "\n");
                const item = lists?.find(f => f.name === target);
                if (item && info) item.count = info.count;
                for (const err of info?.apply_errors || []) toast.error(`Список сохранён, но не применён: ${moduleTitle(err.module)}`, err.error);
                toast.success(`Добавлено в «${target}»: ${fresh.length}`);
                if (current === target) { current = null; await openList(target); } else render();
                h.close();
              } catch (err) {
                toast.error("Не удалось добавить", err.message);
              }
            });
          }
        });
        intro();
      },
    });
  }

  Pages.define({
    id: "lists", title: "Списки", icon: "list", group: "Данные",
    mount(el) {
      root = el;
      root.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Списки</h1>
          </div>
          <button class="btn outline sm" data-act="record">${ic("radar")}Записать домены сайта</button>
        </div>
        <div data-slot="body"></div>`;
      body = root.querySelector("[data-slot=body]");
      root.addEventListener("click", onClick);
      root.addEventListener("input", onInput);
      root.addEventListener("contextmenu", onContext);
      render();
    },
    show() { loadLists(); },
    hide() { if (dirty) flushSave(); },
  });
})();
