"use strict";
/* Проверки: заблокирован ли домен официально (cheburcheck — реестр РКН) и
   достучимся ли мы до него прямо сейчас с этой машины (blockcheck). Один и тот же
   вид на обе проверки — вкладки с доменом/списком, прогрессом и таблицей результатов.
   Результаты списка стримятся пушами: новые строки domорфятся по data-key=домен,
   без перерисовки всей таблицы — списки бывают в сотни доменов. */

(() => {
  let root, body;
  let tab = "rkn";  // "rkn" | "reach"

  let listNames = null;         // кэш lists_all для выпадашек — переживает уход со страницы
  let cheburStatus = null;      // статус реестра РКН (cheburcheck)
  let cheburStatusError = null;

  const CHEBUR_LABELS = { blocked: "БЛОК", free: "свободен", rate: "лимит", error: "ошибка" };
  const BLOCK_LABELS = { ok: "ok", challenge: "CLOUDFLARE", denied: "ОТКАЗ", blocked: "БЛОК", dns: "нет DNS", error: "ошибка" };

  function freshState() {
    return { domain: "", list: "", running: false, expected: 0, done: 0, hits: 0, results: [], onlyProblem: false, error: "" };
  }
  const state = { rkn: freshState(), reach: freshState() };

  // --- строки таблиц по доменам ------------------------------------------------

  function cheburDate(s) { return s ? String(s).slice(0, 10) : ""; }

  function cheburMeta(r) {
    if (r.status === "rate") return "не проверен — лимит запросов";
    if (r.status === "error") return "не проверен — сетевая ошибка";
    const bits = [];
    if (r.status === "blocked") {
      if (r.rkn_domain) bits.push("реестр РКН");
      if (r.subnets?.length) bits.push(`подсети: ${r.subnets.join(", ")}`);
      if (r.cdn?.length) bits.push(`CDN: ${r.cdn.join(", ")}`);
      if (!bits.length) bits.push("заблокирован");
    } else {
      bits.push("в реестрах не найден");
    }
    if (r.geo?.org) bits.push(r.geo.asn ? `${r.geo.org} (${r.geo.asn})` : r.geo.org);
    else if (r.geo?.asn) bits.push(r.geo.asn);
    if (r.rank) bits.push(`популярность #${r.rank}`);
    if (r.last_ok) bits.push(`посл. доступ ${cheburDate(r.last_ok)}`);
    if (r.ptr?.length) bits.push(`PTR: ${r.ptr.join(", ")}`);
    return bits.join(" · ");
  }

  function cheburRowHtml(r) {
    const variant = r.blocked ? "danger" : r.status === "free" ? "success" : "warning";
    const label = CHEBUR_LABELS[r.status] || r.status;
    const chips = [];
    if (r.type) chips.push(r.type);
    if (r.geo?.country) chips.push(r.geo.country);
    const meta = cheburMeta(r);
    const tip = r.ips?.length ? ` data-tip="IP: ${esc(r.ips.join(", "))}"` : "";
    return `
      <tr data-key="${esc(r.target)}"${tip}>
        <td class="shrink">${badgeHtml(label, variant)}</td>
        <td class="mono">${esc(r.target)}${chips.length ? ` <span class="muted">· ${esc(chips.join(" · "))}</span>` : ""}</td>
        <td class="muted chk-meta">${esc(meta)}</td>
      </tr>`;
  }

  function reachRowHtml(r) {
    const variant = r.status === "ok" ? "success" : r.status === "challenge" ? "warning"
      : (r.status === "denied" || r.status === "blocked") ? "danger" : "outline";
    const label = BLOCK_LABELS[r.status] || r.status;
    const detail = [r.ip, r.reason, r.ms != null ? `${r.ms} мс` : null].filter(Boolean).join(" · ");
    return `
      <tr data-key="${esc(r.target)}">
        <td class="shrink">${badgeHtml(label, variant)}</td>
        <td class="mono">${esc(r.target)}</td>
        <td class="muted">${esc(detail)}</td>
      </tr>`;
  }

  const CHECKERS = {
    rkn: {
      id: "rkn", title: "Реестр РКН", icon: "shield-check",
      desc: "Официальная блокировка — домен числится в реестре РКН или в заблокированной подсети (cheburcheck.ru).",
      apiOne: "chebur_check_one", apiStart: "chebur_check_start",
      isHit: r => r.blocked === true,
      isProblem: r => r.status !== "free",
      row: cheburRowHtml,
      summary(st) {
        if (st.running) return `Проверяю ${st.done}/${st.expected}…`;
        if (!st.results.length) return "";
        const total = st.expected || st.results.length;
        return `Заблокировано: <b>${st.hits}/${total}</b> <span class="muted">— БЛОК: домен в реестре РКН или в заблокированной подсети</span>`;
      },
    },
    reach: {
      id: "reach", title: "Доступность", icon: "wifi",
      desc: "Достучимся ли мы до домена прямо сейчас — с текущими winws/DNS/hosts/прокси, как в браузере.",
      apiOne: "block_check_one", apiStart: "block_check_start",
      isHit: r => r.status === "ok",
      isProblem: r => r.status !== "ok",
      row: reachRowHtml,
      summary(st) {
        if (st.running) return `Проверяю ${st.done}/${st.expected}…`;
        if (!st.results.length) return "";
        const total = st.expected || st.results.length;
        return `Достучались: <b>${st.hits}/${total}</b> <span class="muted">— CF пройдёт сам в браузере; ОТКАЗ — бан сайта; БЛОК — RST/таймаут; нет DNS — не резолвится</span>`;
      },
    },
  };

  // --- рендер --------------------------------------------------------------------

  function errorAlert(msg) {
    return `<div class="alert destructive">${ic("circle-alert")}<div class="alert-desc">${esc(msg)}</div></div>`;
  }

  function listOptionsHtml(selected) {
    if (listNames == null) return `<option value="">Загрузка…</option>`;
    if (!listNames.length) return `<option value="">Списков нет</option>`;
    return listNames.map(f =>
      `<option value="${esc(f.name)}"${f.name === selected ? " selected" : ""}>${esc(f.name)} (${fmtNum(f.count)})</option>`).join("");
  }

  function emptyRowsHtml(st) {
    return st.running
      ? `<tr><td colspan="3" class="muted">Жду первые результаты…</td></tr>`
      : `<tr><td colspan="3">${emptyHtml({ icon: "filter", title: "Ничего не найдено", desc: "Отключи фильтр «только проблемные», чтобы увидеть остальные." })}</td></tr>`;
  }

  function toolbarHtml(id, st) {
    return `
      <div class="cluster chk-toolbar">
        <div class="input-group grow">${ic("search")}<input class="input" data-domain="${id}" placeholder="домен, например youtube.com" value="${esc(st.domain)}"></div>
        <button class="btn" data-one="${id}">Проверить домен</button>
        <span class="muted">или список</span>
        <select class="select-native chk-select" data-list="${id}">${listOptionsHtml(st.list)}</select>
        <button class="btn outline" data-start="${id}" ${st.running ? "disabled" : ""}>${st.running ? "Проверяю…" : "Проверить список"}</button>
      </div>`;
  }

  function resultsBlockHtml(id, st) {
    if (!st.results.length && !st.running) return "";
    const cfg = CHECKERS[id];
    const rows = (st.onlyProblem ? st.results.filter(cfg.isProblem) : st.results).map(cfg.row).join("");
    return `
      <div class="stack-sm">
        <div class="between">
          <div class="chk-summary" data-key="summary-${id}">${cfg.summary(st)}</div>
          <label class="check-row"><input type="checkbox" class="checkbox" data-filter="${id}" ${st.onlyProblem ? "checked" : ""}>Только проблемные</label>
        </div>
        ${st.running ? `<div class="progress" data-key="progress-${id}"><i style="transform:scaleX(${st.expected ? st.done / st.expected : 0})"></i></div>` : ""}
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Статус</th><th>Домен</th><th>Детали</th></tr></thead>
            <tbody data-key="tbody-${id}">${rows || emptyRowsHtml(st)}</tbody>
          </table>
        </div>
      </div>`;
  }

  function statusBannerHtml() {
    if (cheburStatusError) {
      return `<div class="alert warning">${ic("triangle-alert")}<div class="alert-title">cheburcheck недоступен</div><div class="alert-desc">${esc(cheburStatusError)} — проверка по реестру сейчас офлайн.</div></div>`;
    }
    if (!cheburStatus) return skeletonHtml(1, 44);
    const upd = cheburStatus.last_update ? new Date(cheburStatus.last_update).toLocaleString("ru-RU") : "?";
    const cnt = cheburStatus.domain_count != null ? fmtNum(cheburStatus.domain_count) : "?";
    const v4 = cheburStatus.v4_count ? `, ${fmtNum(Math.round(cheburStatus.v4_count / 1e6))} млн IPv4` : "";
    return `<div class="alert">${ic("info")}<div class="alert-title">cheburcheck v${esc(cheburStatus.version || "?")}</div><div class="alert-desc">Реестр РКН: ${cnt} доменов${v4}, обновлён ${esc(upd)}</div></div>`;
  }

  function sectionHtml(id) {
    const cfg = CHECKERS[id], st = state[id];
    return `
      ${id === "rkn" ? statusBannerHtml() : ""}
      <div class="card">
        <div class="card-header">
          <div class="card-title">${ic(cfg.icon)}${cfg.title}</div>
          <div class="card-description">${esc(cfg.desc)}</div>
        </div>
        <div class="card-content stack-sm">
          ${toolbarHtml(id, st)}
          ${st.error ? errorAlert(st.error) : ""}
          ${resultsBlockHtml(id, st)}
        </div>
      </div>`;
  }

  function render() {
    morph(body, `
      <div class="tabs-list" data-key="tabs">
        <button class="tabs-trigger" role="tab" aria-selected="${tab === "rkn"}" data-tab="rkn">${ic("shield-check")}Реестр РКН</button>
        <button class="tabs-trigger" role="tab" aria-selected="${tab === "reach"}" data-tab="reach">${ic("wifi")}Доступность</button>
      </div>
      ${sectionHtml(tab)}`);
  }

  // точечное обновление во время стрима результатов — без пересборки всей страницы
  function updateProgress(id) {
    const st = state[id], cfg = CHECKERS[id];
    const tbody = body?.querySelector(`[data-key="tbody-${id}"]`);
    if (tbody) {
      const rows = (st.onlyProblem ? st.results.filter(cfg.isProblem) : st.results).map(cfg.row).join("");
      morph(tbody, rows || emptyRowsHtml(st));
    }
    const sum = body?.querySelector(`[data-key="summary-${id}"]`);
    if (sum) sum.innerHTML = cfg.summary(st);
    const bar = body?.querySelector(`[data-key="progress-${id}"] i`);
    if (bar) bar.style.transform = `scaleX(${st.expected ? st.done / st.expected : 0})`;
  }

  // --- данные ----------------------------------------------------------------

  async function loadListNames() {
    try {
      listNames = await api("lists_all");
    } catch {
      listNames = listNames || [];
    }
    if (body) render();
  }

  async function loadCheburStatus() {
    try {
      cheburStatus = await api("chebur_status");
      cheburStatusError = null;
    } catch (e) {
      cheburStatusError = e.message;
    }
    if (body && tab === "rkn") render();
  }

  async function checkOne(id) {
    const cfg = CHECKERS[id], st = state[id];
    const domain = st.domain.trim();
    if (!domain) return;
    st.error = ""; st.running = false; st.expected = 0; st.done = 0; st.hits = 0; st.results = [];
    render();
    try {
      const r = await api(cfg.apiOne, domain);
      if (r) { st.results = [r]; st.hits = cfg.isHit(r) ? 1 : 0; st.done = 1; }
    } catch (e) {
      st.error = e.message;
    }
    render();
  }

  async function checkList(id) {
    const cfg = CHECKERS[id], st = state[id];
    if (st.running) return;
    const name = st.list;
    if (!name) { toast.warning("Список не выбран", "Выбери список в выпадающем меню."); return; }
    st.error = ""; st.results = []; st.done = 0; st.hits = 0;
    render();
    try {
      const info = await api(cfg.apiStart, name);
      st.expected = info?.total || 0;
      st.running = true;
    } catch (e) {
      st.error = e.message;
    }
    render();
  }

  function pushResult(id, r) {
    const st = state[id], cfg = CHECKERS[id];
    st.done++;
    if (cfg.isHit(r)) st.hits++;
    st.results.push(r);
    if (body && tab === id) updateProgress(id);
  }
  function pushDone(id) {
    state[id].running = false;
    if (body && tab === id) render();
  }

  onPush("cheburResult", r => pushResult("rkn", r));
  onPush("cheburDone", () => pushDone("rkn"));
  onPush("blockResult", r => pushResult("reach", r));
  onPush("blockDone", () => pushDone("reach"));

  // --- события -----------------------------------------------------------------

  function onClick(e) {
    const t = e.target.closest("[data-tab]");
    if (t) { tab = t.dataset.tab; render(); return; }
    const one = e.target.closest("[data-one]");
    if (one) { withBusy(one, () => checkOne(one.dataset.one)); return; }
    const start = e.target.closest("[data-start]");
    if (start) { withBusy(start, () => checkList(start.dataset.start)); return; }
  }

  function onFieldEvent(e) {
    const dom = e.target.closest("[data-domain]");
    if (dom) { state[dom.dataset.domain].domain = dom.value; return; }
    const listSel = e.target.closest("[data-list]");
    if (listSel) { state[listSel.dataset.list].list = listSel.value; return; }
    const filt = e.target.closest("[data-filter]");
    if (filt) { state[filt.dataset.filter].onlyProblem = filt.checked; render(); }
  }

  Pages.define({
    id: "checks", title: "Проверки", icon: "scan-search", group: "Данные",
    mount(el) {
      root = el;
      root.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Проверки</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;
      body = root.querySelector("[data-slot=body]");
      root.addEventListener("click", onClick);
      root.addEventListener("input", onFieldEvent);
      root.addEventListener("change", onFieldEvent);
      root.addEventListener("keydown", e => {
        if (e.key === "Enter" && e.target.matches("[data-domain]")) checkOne(e.target.dataset.domain);
      });
      render();
    },
    show() {
      loadListNames();
      loadCheburStatus();
    },
  });
})();
