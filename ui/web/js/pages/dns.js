"use strict";
/* DNS — переключатель системного DNS (аналог DNS Jumper).

   Источник "dns" в хабе ленивый (dns_state гоняет PowerShell — секунды), поэтому
   его включаем ctx.watch(["dns"]) только пока страница открыта. Пока данных нет —
   скелетон, остальное (заголовок, карточки) рисуется сразу. Проба возможностей
   и её настройки в хаб не входят — грузятся один раз при первом заходе. */

(() => {
  let root;
  let selectedAdapter = null;   // index адаптера, выбранный пользователем
  let pingResults = {};         // provider id -> {servers:[{server,ok,ms}]}
  let applying = {};            // provider id -> true, пока идёт dns_set
  let probing = {};             // provider id -> true, пока идёт dns_probe
  let probeResults = {};        // provider id -> результат пробы | {error}
  let probeConfig = null;
  let probeConfigTimer = 0;

  function dnsState() { return Store.get("dns"); }
  function adapters() { return dnsState()?.adapters || []; }

  function currentAdapter() {
    const list = adapters();
    if (!list.length) return null;
    if (selectedAdapter != null) {
      const found = list.find(a => a.index === selectedAdapter);
      if (found) return found;
    }
    return list[0];
  }

  function isActiveProvider(p, a) {
    const cur = a?.dns || [];
    if (!cur.length) return false;
    const set = new Set(p.servers || []);
    return cur.every(ip => set.has(ip));
  }

  function adapterOptionLabel(a) {
    const dot = a.status === "Up" ? "●" : "○";
    return `${dot} ${a.name} — ${a.desc}${a.physical ? "" : " · вирт."}`;
  }

  // --- сортировка провайдеров по скорости ---------------------------------------

  function bestMs(p) {
    const r = pingResults[p.id];
    if (!r) return Infinity;
    const ok = (r.servers || []).filter(s => s.ok);
    return ok.length ? Math.min(...ok.map(s => s.ms)) : Infinity - 1;
  }

  // Порядок по скорости фиксируется один раз — после первого полного прохода
  // пингов. Пересортировка на каждом тике двигала бы строки под курсором, и клик
  // по «Применить» попадал бы в соседнего провайдера.
  let fixedOrder = null;

  function sortedProviders() {
    const list = (dnsState()?.providers || []).slice();
    if (!fixedOrder) return list;
    const pos = id => { const i = fixedOrder.indexOf(id); return i < 0 ? Infinity : i; };
    return list.sort((a, b) => pos(a.id) - pos(b.id));
  }

  // --- автопинг: все провайдеры параллельно на каждый тик, без наложения --------

  // результат рисуется сразу по приходу: недоступный сервер отвечает таймаутом
  // в секунды и не должен держать «…» у всех остальных
  const renderSoon = rafThrottle(() => render());

  async function pingAll() {
    const list = dnsState()?.providers || [];
    if (!list.length) return;
    await Promise.allSettled(list.map(async p => {
      try { pingResults[p.id] = await api("dns_ping_one", p.id); }
      catch { pingResults[p.id] = { servers: (p.servers || []).map(s => ({ server: s, ok: false, ms: null })) }; }
      renderSoon();
    }));
    if (!fixedOrder || fixedOrder.length !== list.length) {
      fixedOrder = list.slice().sort((a, b) => bestMs(a) - bestMs(b)).map(p => p.id);
      renderSoon();
    }
  }

  // --- действия провайдера --------------------------------------------------------

  async function onApply(id) {
    const a = currentAdapter();
    if (!a) return toast.error("Адаптер не выбран.");
    applying[id] = true;
    render();
    try {
      const p = await api("dns_set", a.index, id);
      toast.success(`DNS → ${p?.name || id}`, p?.encrypted ? "Шифрование DoH включено, кэш сброшен." : "Кэш сброшен.");
    } catch (e) {
      toast.error("Не удалось применить", e.message);
    } finally {
      delete applying[id];
      render();
      api("hub_refresh", ["dns"]).catch(() => {});
    }
  }

  async function onReset() {
    const a = currentAdapter();
    if (!a) return toast.error("Адаптер не выбран.");
    try {
      await api("dns_reset", a.index);
      toast.success("DNS сброшен на DHCP.");
      api("hub_refresh", ["dns"]).catch(() => {});
    } catch (e) { toast.error("Не удалось сбросить", e.message); }
  }

  async function onProbe(id) {
    probing[id] = true;
    render();
    try {
      probeResults[id] = await api("dns_probe", id);
    } catch (e) {
      probeResults[id] = { error: e.message };
    } finally {
      delete probing[id];
      render();
    }
  }

  async function onDelete(id) {
    const p = (dnsState()?.providers || []).find(x => x.id === id);
    const ok = await confirmDialog({
      title: "Удалить провайдера?",
      description: `Провайдер «${p?.name || id}» будет удалён.`,
      confirmText: "Удалить", destructive: true,
    });
    if (!ok) return;
    try {
      await api("dns_delete_provider", id);
      toast.success("Провайдер удалён.");
      api("hub_refresh", ["dns"]).catch(() => {});
    } catch (e) { toast.error("Не удалось удалить", e.message); }
  }

  function openAddProvider() {
    openDialog({
      title: "Свой DNS-провайдер",
      wide: true,
      body: `
        <div class="stack-sm">
          <div class="field"><label class="label">Название</label>
            <input class="input" data-f="name" placeholder="Мой DNS"></div>
          <div class="row">
            <div class="field"><label class="label">Основной DNS</label>
              <input class="input mono" data-f="ip1" placeholder="1.1.1.1"></div>
            <div class="field"><label class="label">Дополнительный</label>
              <input class="input mono" data-f="ip2" placeholder="необязательно"></div>
          </div>
          <div class="field"><label class="label">IPv6</label>
            <input class="input mono" data-f="ip6" placeholder="через пробел, необязательно"></div>
          <div class="row">
            <div class="field"><label class="label">DoH</label>
              <input class="input mono" data-f="doh" placeholder="https://…/dns-query"></div>
            <div class="field"><label class="label">DoT</label>
              <input class="input mono" data-f="dot" placeholder="dns.example.com"></div>
          </div>
          <label class="check-row"><input type="checkbox" class="checkbox" data-f="unblock"><span>Обходит блокировки (показывать во вкладке Hosts)</span></label>
          <label class="check-row"><input type="checkbox" class="checkbox" data-f="filter"><span>Режет рекламу, трекеры и фишинг</span></label>
        </div>`,
      footer: `<button class="btn outline" data-close>Отмена</button><button class="btn" data-ok>Добавить</button>`,
      onMount(h) {
        const val = f => h.el.querySelector(`[data-f="${f}"]`).value.trim();
        const chk = f => h.el.querySelector(`[data-f="${f}"]`).checked;
        h.el.querySelector("[data-ok]").addEventListener("click", () => withBusy(h.el.querySelector("[data-ok]"), async () => {
          try {
            await api("dns_add_provider", val("name"), [val("ip1"), val("ip2")],
              val("ip6"), val("doh"), val("dot"), chk("unblock"), chk("filter"));
            toast.success("Провайдер добавлен.");
            h.close(true);
            api("hub_refresh", ["dns"]).catch(() => {});
          } catch (e) { toast.error("Не удалось добавить", e.message); }
        }));
      },
    });
  }

  // --- проба возможностей: настройки тест-доменов --------------------------------

  function scheduleProbeConfigSave() {
    clearTimeout(probeConfigTimer);
    probeConfigTimer = setTimeout(async () => {
      const bypass = root.querySelector("[data-probe-bypass]")?.value ?? "";
      const ad = root.querySelector("[data-probe-ad]")?.value ?? "";
      try { probeConfig = await api("dns_set_probe_config", bypass, ad); }
      catch (e) { toast.error("Не удалось сохранить домены пробы", e.message); }
    }, 500);
  }

  // --- рендер ----------------------------------------------------------------------

  function adminAlertHtml() {
    if (Store.get("app")?.admin !== false) return "";
    return `<div class="alert warning" data-key="admin-alert">${ic("triangle-alert")}
      <div class="alert-title">Нет прав администратора</div>
      <div class="alert-desc">Смена системного DNS потребует прав администратора.</div></div>`;
  }

  function adapterCardHtml() {
    const st = dnsState();
    if (!st) return skeletonHtml(2, 36);
    const list = st.adapters || [];
    if (!list.length) return emptyHtml({ icon: "wifi-off", title: "Сетевые адаптеры не найдены" });
    const a = currentAdapter();
    const info = a ? [
      a.ipv4?.length ? `IP ${a.ipv4.join(", ")}` : null,
      a.dns?.length ? `DNS ${a.dns.join(", ")}` : "DNS автоматически (DHCP)",
      a.speed || null,
    ].filter(Boolean).join(" · ") : "";
    return `
      <div class="row">
        <div class="field">
          <label class="label">Сетевой адаптер</label>
          <select class="select-native" data-adapter>
            ${list.map(x => `<option value="${x.index}" ${x.index === a?.index ? "selected" : ""}>${esc(adapterOptionLabel(x))}</option>`).join("")}
          </select>
        </div>
        <button class="btn outline" data-reset>${ic("rotate-ccw")}Сбросить (DHCP)</button>
      </div>
      <div class="muted dns-current">${esc(info)}</div>`;
  }

  function providerBadges(p) {
    const b = [];
    if (p.servers?.length) b.push(badgeHtml("IPv4", "outline"));
    if (p.ipv6?.length) b.push(badgeHtml("IPv6", "outline"));
    if (p.doh) b.push(badgeHtml("DoH", "info"));
    if (p.dot) b.push(badgeHtml("DoT", "info"));
    if (p.unblock) b.push(badgeHtml("обход", "warning"));
    if (p.filter) b.push(badgeHtml("защита", "success"));
    return b.join("");
  }

  function pingCellHtml(id) {
    const r = pingResults[id];
    if (!r) return `<span class="muted">…</span>`;
    return (r.servers || []).map(s => s.ok
      ? `<span class="dns-ping-item"><span class="dot ${s.ms < 60 ? "on" : s.ms < 200 ? "warn" : "err"}"></span>${fmtNum(s.ms)} мс</span>`
      : `<span class="dns-ping-item"><span class="dot err"></span>—</span>`
    ).join("");
  }

  function probeMark(v) {
    return v === true ? `<span class="dns-probe-ok">${ic("circle-check")}</span>`
         : v === false ? `<span class="dns-probe-fail">${ic("circle-x")}</span>`
         : `<span class="muted">—</span>`;
  }

  function probeHtml(id) {
    if (probing[id]) return `<div class="dns-probe muted">Проверяю…</div>`;
    const r = probeResults[id];
    if (!r) return "";
    if (r.error) return `<div class="dns-probe"><span class="dns-probe-fail">${ic("circle-x")}${esc(r.error)}</span></div>`;
    if (!r.reachable) return `<div class="dns-probe"><span class="dns-probe-fail">${ic("circle-x")}сервер не ответил</span></div>`;
    const doms = Object.keys(r.unblock_detail || {}).join(", ");
    return `<div class="dns-probe">
      <span>DNSSEC ${probeMark(r.dnssec)}</span>
      <span>обход${doms ? ` (${esc(doms)})` : ""} ${probeMark(r.unblock)}</span>
      <span>реклама ${probeMark(r.filter)}</span>
    </div>`;
  }

  function providerRowHtml(p) {
    const a = currentAdapter();
    const active = a && isActiveProvider(p, a);
    const servers = [...(p.servers || []), ...(p.ipv6 || [])].join(" · ");
    const endpoints = [p.doh ? `DoH ${p.doh}` : "", p.dot ? `DoT ${p.dot}` : ""].filter(Boolean).join(" · ");
    return `
    <div class="item dns-row" data-key="dns-${esc(p.id)}" ${active ? 'aria-selected="true"' : ""}>
      <div class="item-media">${ic(p.unblock ? "shield-check" : "globe")}</div>
      <div class="item-body">
        <div class="dns-row-title">${esc(p.name)}${active ? badgeHtml("активен", "success", "check") : ""}${providerBadges(p)}</div>
        <div class="item-desc">${esc(servers)}${endpoints ? ` · ${esc(endpoints)}` : ""}</div>
        ${probeHtml(p.id)}
      </div>
      <div class="dns-ping">${pingCellHtml(p.id)}</div>
      <div class="item-actions">
        <button class="btn ghost xs" data-probe="${esc(p.id)}" ${probing[p.id] ? "disabled" : ""}>${probing[p.id] ? ic("loader-circle", "spin") : ic("scan-search")}Проба</button>
        ${active
          ? `<button class="btn secondary sm" disabled>${ic("check")}Активен</button>`
          : `<button class="btn outline sm" data-use="${esc(p.id)}" ${applying[p.id] ? "disabled" : ""}>${applying[p.id] ? ic("loader-circle", "spin") : ""}Применить</button>`}
        ${!p.builtin ? `<button class="btn ghost xs icon-btn" data-del="${esc(p.id)}" data-tip="Удалить">${ic("trash-2")}</button>` : ""}
      </div>
    </div>`;
  }

  function providersListHtml() {
    const st = dnsState();
    if (!st) return skeletonHtml(4, 64);
    const list = sortedProviders();
    if (!list.length) return emptyHtml({ icon: "network", title: "Провайдеров нет" });
    return `<div class="item-list" data-key="dns-list">${list.map(providerRowHtml).join("")}</div>`;
  }

  function probeConfigHtml() {
    if (!probeConfig) return skeletonHtml(2, 36);
    return `
      <div class="field">
        <label class="label">Домены для проверки обхода</label>
        <input class="input mono" data-probe-bypass value="${esc((probeConfig.bypass || []).join(" "))}" placeholder="rutracker.org">
        <p class="hint">Указывай реально заблокированные у тебя домены — гео-блок (напр. chatgpt.com) для этой пробы не годится.</p>
      </div>
      <div class="field">
        <label class="label">Домен-маркер рекламы</label>
        <input class="input mono" data-probe-ad value="${esc(probeConfig.ad || "")}" placeholder="doubleclick.net">
      </div>`;
  }

  function render() {
    morph(root.querySelector("[data-slot=body]"), `
      ${adminAlertHtml()}
      <div class="card compact" data-key="card-adapter">
        <div class="card-header">
          <div class="card-title">${ic("wifi")}Адаптер</div>
          <div class="card-description">Куда применяется DNS-провайдер</div>
        </div>
        <div class="card-content stack-sm">${adapterCardHtml()}</div>
      </div>
      <div class="card compact" data-key="card-providers">
        <div class="card-header">
          <div class="card-title">${ic("network")}DNS-провайдеры</div>
          <div class="card-description">Список отсортирован по скорости ответа</div>
          <div class="card-action"><button class="btn ghost sm" data-add-provider>${ic("plus")}Добавить</button></div>
        </div>
        <div class="card-content">${providersListHtml()}</div>
      </div>
      <div class="card compact" data-key="card-probe">
        <div class="card-header">
          <div class="card-title">${ic("scan-search")}Проба возможностей</div>
          <div class="card-description">Тест-домены для кнопки «Проба» у каждого провайдера (DNSSEC, обход, реклама)</div>
        </div>
        <div class="card-content stack-sm">${probeConfigHtml()}</div>
      </div>`);
  }

  Pages.define({
    id: "dns", title: "DNS", icon: "network", group: "Сеть",
    mount(el) {
      root = el;
      el.innerHTML = `
        <div class="page-head">
          <div>
            <h1 class="page-title">DNS</h1>
          </div>
        </div>
        <div class="stack" data-slot="body"></div>`;

      el.addEventListener("click", e => {
        if (e.target.closest("[data-add-provider]")) return openAddProvider();
        if (e.target.closest("[data-reset]")) return onReset();
        const use = e.target.closest("[data-use]");
        if (use) return onApply(use.dataset.use);
        const probe = e.target.closest("[data-probe]");
        if (probe) return onProbe(probe.dataset.probe);
        const del = e.target.closest("[data-del]");
        if (del) return onDelete(del.dataset.del);
      });
      el.addEventListener("change", e => {
        if (e.target.closest("[data-adapter]")) {
          selectedAdapter = Number(e.target.value);
          render();
        }
      });
      el.addEventListener("input", e => {
        if (e.target.closest("[data-probe-bypass], [data-probe-ad]")) scheduleProbeConfigSave();
      });

      api("dns_probe_config").then(c => { probeConfig = c; render(); }).catch(() => {});
    },
    show(ctx) {
      ctx.watch(["dns"]);
      ctx.on(["dns", "app"], render);
      render();
      ctx.every(2500, pingAll);
    },
  });
})();
