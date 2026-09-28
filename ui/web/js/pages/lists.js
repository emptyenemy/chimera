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
    } catch (e) {
      dirty = true;  // не терять правки, если сохранить не вышло
      if (current === name) { errorMsg = e.message; setStatus("error"); }
    }
  }

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
      await api("lists_delete", name);
      toast.success(`Список ${name} удалён`);
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

  Pages.define({
    id: "lists", title: "Списки", icon: "list", group: "Данные",
    mount(el) {
      root = el;
      root.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Списки</h1>
            <p class="page-desc">Домены и IP по сервисам — общий источник для прокси, hosts и запрета DPI</p>
          </div>
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
