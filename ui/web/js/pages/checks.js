"use strict";
/* Проверка сайтов: одно поле — один ответ по каждому сайту. Внутри две проверки
   идут параллельно — есть ли сайт в реестре РКН (cheburcheck) и открывается ли он
   прямо сейчас с этой машины с учётом обхода (blockcheck), — а в таблице они
   сведены в итог человеческими словами: «Открывается», «Работает через обход»,
   «Заблокирован» и т.п. Списки стримятся пушами: строки морфятся по data-key=сайт,
   без перерисовки всей таблицы — списки бывают в сотни доменов. */

(() => {
  let root, body;
  let listNames = null;          // lists_all для выпадашки — переживает уход со страницы
  let registryDown = null;       // текст ошибки сервиса реестра, если он недоступен
  let input = "";                // что введено в поле
  let onlyProblems = false;

  // сайт -> { rkn, reach } — результаты двух проверок; порядок вставки = порядок строк
  let results = new Map();
  let run = null;                // { total, rknDone, reachDone, list } — идёт проверка

  const PARALLEL = 4;            // для введённых вручную: реестр публичный, не долбим его

  // --- разбор ввода: ссылки, несколько сайтов через пробел/запятую ---------------

  function parseTargets(text) {
    const seen = new Set();
    for (let raw of String(text).split(/[\s,;]+/)) {
      raw = raw.trim().replace(/^[a-z]+:\/\//i, "").split(/[/?#]/)[0].replace(/:\d+$/, "").replace(/^www\./i, "")
        .toLowerCase();
      if (/^[a-z0-9.-]+\.[a-z0-9-]{2,}$/i.test(raw)) seen.add(raw);
    }
    return [...seen];
  }

  // --- итог по двум проверкам ------------------------------------------------------

  // Реестр различает две вещи: в него внесён сам домен — или только адрес/подсеть, где
  // сайт живёт (часто общая CDN вроде Akamai). Для пользователя это разный смысл:
  // первое — сайт блокируют, второе — он может открываться и сам по себе.
  const inRegistry = r => r?.blocked === true && !!r.rkn_domain;
  const ipInRegistry = r => r?.blocked === true && !r.rkn_domain;

  // { label, tone, note } — что сказать пользователю про сайт
  function verdict(rkn, reach) {
    if (!reach) return { label: "Проверяю…", tone: "pending", note: "" };
    const s = reach.status;
    if (s === "ok" || s === "challenge") {
      const cf = s === "challenge" ? "Cloudflare проверит браузер" : "";
      return inRegistry(rkn)
        ? { label: "Работает через обход", tone: "success", note: ["в реестре РКН", cf].filter(Boolean).join(" · ") }
        : { label: "Открывается", tone: "success", note: cf };
    }
    if (inRegistry(rkn)) return { label: "Заблокирован", tone: "danger", note: "в реестре РКН — включи обход или прокси для него" };
    if (ipInRegistry(rkn)) return { label: "Заблокирован по IP", tone: "danger", note: "адрес сайта в заблокированной подсети — поможет прокси" };
    if (s === "denied") return { label: "Сайт отказал", tone: "warning", note: reach.reason || "бан по стране или IP" };
    if (s === "dns") return { label: "Нет DNS", tone: "warning", note: "имя не разрешается" };
    if (s === "blocked") return { label: "Не открывается", tone: "danger", note: reach.reason || "соединение обрывается" };
    return { label: "Ошибка проверки", tone: "muted", note: reach.reason || "" };
  }

  const isProblem = ({ rkn, reach }) => {
    const t = verdict(rkn, reach).tone;
    return t === "danger" || t === "warning" || t === "muted";
  };

  // --- разметка --------------------------------------------------------------------

  function registryCell(rkn) {
    if (!rkn) return registryDown ? `<span class="muted">—</span>` : `<span class="muted">…</span>`;
    if (rkn.status === "rate" || rkn.status === "error") return `<span class="muted" data-tip="Реестр не ответил">—</span>`;
    if (inRegistry(rkn)) return `<span class="chk-reg is-in">домен</span>`;
    if (ipInRegistry(rkn)) return `<span class="chk-reg is-ip" data-tip="${esc([...(rkn.subnets || []), ...(rkn.cdn || [])].join(", "))}">по IP</span>`;
    return `<span class="muted">нет</span>`;
  }

  function rowHtml(site, { rkn, reach }) {
    const v = verdict(rkn, reach);
    const ms = reach?.ms != null && (reach.status === "ok" || reach.status === "challenge") ? `${fmtNum(reach.ms)} мс` : "";
    return `
      <tr data-key="${esc(site)}"${reach?.ip ? ` data-tip="IP ${esc(reach.ip)}"` : ""}>
        <td class="mono chk-site">${esc(site)}</td>
        <td><span class="chk-verdict ${v.tone}"><span class="dot ${v.tone === "success" ? "on" : v.tone === "danger" ? "err" : v.tone === "warning" ? "warn" : ""}"></span>${esc(v.label)}</span>
          ${v.note ? `<div class="chk-note">${esc(v.note)}</div>` : ""}</td>
        <td class="shrink">${registryCell(rkn)}</td>
        <td class="shrink num muted">${ms}</td>
      </tr>`;
  }

  function summaryHtml() {
    const all = [...results.values()];
    if (run) return `Проверяю ${Math.min(run.reachDone, run.total)} из ${run.total}…`;
    if (!all.length) return "";
    const open = all.filter(r => verdict(r.rkn, r.reach).tone === "success").length;
    const reg = all.filter(r => inRegistry(r.rkn)).length;
    return `Открывается <b>${open} из ${all.length}</b>${reg ? ` · в реестре РКН <b>${reg}</b>` : ""}`;
  }

  function rowsHtml() {
    const rows = [...results.entries()].filter(([, r]) => !onlyProblems || isProblem(r));
    if (!rows.length) {
      return `<tr><td colspan="4">${emptyHtml({ icon: "circle-check", title: "Проблемных сайтов нет" })}</td></tr>`;
    }
    return rows.map(([site, r]) => rowHtml(site, r)).join("");
  }

  function listOptionsHtml() {
    if (listNames == null) return `<option value="">Загрузка…</option>`;
    return `<option value="" selected hidden>Проверить список…</option>` + listNames.map(l =>
      `<option value="${esc(l.name)}">${esc(l.name)} · ${fmtNum(l.count)}</option>`).join("");
  }

  function progress() {
    if (!run || !run.total) return 0;
    return Math.min(1, (run.rknDone + run.reachDone) / (run.total * 2));
  }

  function resultsHtml() {
    if (!results.size) return "";
    return `
      <div class="card compact" data-key="results">
        <div class="card-content stack-sm">
          <div class="between">
            <div class="chk-summary" data-key="summary">${summaryHtml()}</div>
            <label class="check-row"><input type="checkbox" class="checkbox" data-only-problems ${onlyProblems ? "checked" : ""}>Только проблемные</label>
          </div>
          ${run ? `<div class="progress" data-key="progress"><i style="transform:scaleX(${progress()})"></i></div>` : ""}
          <div class="table-wrap">
            <table class="table chk-table">
              <thead><tr><th>Сайт</th><th>Итог</th><th>Реестр РКН</th><th>Ответ</th></tr></thead>
              <tbody data-key="tbody">${rowsHtml()}</tbody>
            </table>
          </div>
        </div>
      </div>`;
  }

  function render() {
    morph(body, `
      <div class="card compact" data-key="form">
        <div class="card-content stack-sm">
          <div class="chk-form">
            <div class="input-group grow">${ic("search")}
              <input class="input" data-input placeholder="Сайт или ссылка — можно несколько через пробел" value="${esc(input)}" autocomplete="off" spellcheck="false">
            </div>
            <button class="btn" data-check ${run ? "disabled" : ""}>Проверить</button>
            <select class="select-native chk-list" data-list ${run || !listNames?.length ? "disabled" : ""}>${listOptionsHtml()}</select>
          </div>
          ${registryDown ? `<p class="hint chk-warn">${ic("triangle-alert")}Реестр РКН сейчас недоступен — проверяю только, открываются ли сайты.</p>` : ""}
        </div>
      </div>
      ${resultsHtml()}`);
  }

  // во время стрима — только таблица, итог и прогресс, без пересборки страницы
  function refreshLive() {
    const tbody = body?.querySelector('[data-key="tbody"]');
    if (!tbody) return render();
    morph(tbody, rowsHtml());
    const sum = body.querySelector('[data-key="summary"]');
    if (sum) sum.innerHTML = summaryHtml();
    const bar = body.querySelector('[data-key="progress"] i');
    if (bar) bar.style.transform = `scaleX(${progress()})`;
  }

  // --- проверка ----------------------------------------------------------------------

  function put(site, key, value) {
    const cur = results.get(site) || { rkn: null, reach: null };
    results.set(site, { ...cur, [key]: value });
  }

  function finishIfDone() {
    if (run && run.rknDone >= run.total && run.reachDone >= run.total) {
      run = null;
      render();
    } else {
      refreshLive();
    }
  }

  // введённые вручную: обе проверки на каждый сайт, по PARALLEL сайтов разом
  async function checkTyped() {
    const sites = parseTargets(input);
    if (!sites.length) { toast.warning("Не похоже на адрес сайта", "Например: youtube.com или https://discord.com/app"); return; }
    results = new Map(sites.map(s => [s, { rkn: null, reach: null }]));
    run = { total: sites.length, rknDone: 0, reachDone: 0 };
    render();
    const one = async site => {
      await Promise.all([
        api("block_check_one", site)
          .then(r => put(site, "reach", r), e => put(site, "reach", { status: "error", reason: e.message }))
          .finally(() => { run.reachDone++; }),
        (registryDown ? Promise.resolve({ status: "error" }) : api("chebur_check_one", site))
          .then(r => put(site, "rkn", r), () => put(site, "rkn", { status: "error" }))
          .finally(() => { run.rknDone++; }),
      ]);
      finishIfDone();
    };
    const queue = [...sites];
    await Promise.all(Array.from({ length: Math.min(PARALLEL, queue.length) }, async () => {
      while (queue.length) await one(queue.shift());
    }));
  }

  // список: обе проверки идут на бэкенде и стримятся пушами
  async function checkList(name) {
    if (!name || run) return;
    results = new Map();
    run = { total: 0, rknDone: 0, reachDone: 0, list: name };
    render();
    try {
      const reach = await api("block_check_start", name);
      run.total = reach?.total || 0;
      if (registryDown) run.rknDone = run.total;
      else {
        try { await api("chebur_check_start", name); } catch { run.rknDone = run.total; }
      }
    } catch (e) {
      run = null;
      toast.error("Не удалось проверить список", e.message);
    }
    render();
  }

  function onReach(r) {
    if (!run) return;
    put(r.target, "reach", r);
    run.reachDone++;
    finishIfDone();
  }
  function onRkn(r) {
    if (!run) return;
    put(r.target, "rkn", r);
    run.rknDone++;
    finishIfDone();
  }

  onPush("blockResult", onReach);
  onPush("cheburResult", onRkn);
  // «Done» только страхуют: итог считается по количеству пришедших ответов
  onPush("blockDone", () => { if (run) { run.reachDone = run.total; finishIfDone(); } });
  onPush("cheburDone", () => { if (run) { run.rknDone = run.total; finishIfDone(); } });

  // --- данные ----------------------------------------------------------------------

  async function loadListNames() {
    try { listNames = await api("lists_all"); } catch { listNames = listNames || []; }
    if (body) render();
  }

  async function loadRegistryStatus() {
    try { await api("chebur_status"); registryDown = null; } catch (e) { registryDown = e.message; }
    if (body) render();
  }

  Pages.define({
    id: "checks", title: "Проверка сайтов", icon: "scan-search", group: "Данные",
    mount(el) {
      root = el;
      root.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">Проверка сайтов</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;
      body = root.querySelector("[data-slot=body]");
      root.addEventListener("click", e => {
        const b = e.target.closest("[data-check]");
        if (b && !b.disabled) withBusy(b, checkTyped);
      });
      root.addEventListener("input", e => {
        if (e.target.matches("[data-input]")) input = e.target.value;
      });
      root.addEventListener("change", e => {
        if (e.target.matches("[data-list]")) { const name = e.target.value; e.target.value = ""; checkList(name); }
        if (e.target.matches("[data-only-problems]")) { onlyProblems = e.target.checked; render(); }
      });
      root.addEventListener("keydown", e => {
        if (e.key === "Enter" && e.target.matches("[data-input]") && !run) checkTyped();
      });
      render();
    },
    show() {
      loadListNames();
      loadRegistryStatus();
    },
  });
})();
