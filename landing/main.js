// Интерактивный макет окна: вкладки разделов и включатели.
(function () {
  const demo = document.getElementById('demo');
  if (!demo) return;

  const tabs = Array.from(demo.querySelectorAll('[role="tab"]'));

  function select(tab, focus) {
    tabs.forEach(function (t) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
  }

  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { select(tab); });
    tab.addEventListener('keydown', function (e) {
      const key = e.key;
      if (key !== 'ArrowDown' && key !== 'ArrowUp' && key !== 'ArrowRight' && key !== 'ArrowLeft') return;
      e.preventDefault();
      const step = key === 'ArrowDown' || key === 'ArrowRight' ? 1 : -1;
      select(tabs[(i + step + tabs.length) % tabs.length], true);
    });
  });

  function paint(sw) {
    const on = sw.getAttribute('aria-checked') === 'true';
    const panel = sw.closest('.panel');
    panel.querySelector('[data-state]').textContent = on ? sw.dataset.on : sw.dataset.off;
    panel.querySelector('.dot').classList.toggle('on', on);
  }

  // Стратегии: сервисы «открываются» по очереди, когда включаешь стратегию.
  const strategySw = document.getElementById('sw-strategy');
  let strategyTimers = [];
  // Вызывается из общего обработчика включателей уже после смены aria-checked.
  function showAccess(on) {
    strategySw.classList.remove('hint');
    document.getElementById('strategy-tip').hidden = true;
    // отложенные смены от прошлого клика отменяем, иначе они перекрасят уже выключенное
    strategyTimers.forEach(clearTimeout);
    strategyTimers = [];
    demo.querySelectorAll('#p-strategies .chk').forEach(function (el, i) {
      function apply() {
        el.classList.toggle('ok', on);
        el.classList.toggle('bad', !on);
        el.textContent = on ? 'Доступен' : 'Недоступен';
      }
      if (on && i > 0) strategyTimers.push(setTimeout(apply, 90 * i));
      else apply();
    });
  }

  // DNS: выбор сервера — одиночный выбор со стрелками.
  const opts = Array.from(demo.querySelectorAll('.opt'));
  function pick(opt, focus) {
    opts.forEach(function (o) {
      o.setAttribute('aria-checked', String(o === opt));
      o.tabIndex = o === opt ? 0 : -1;
    });
    const panel = opt.closest('.panel');
    panel.querySelector('#dns-state').textContent = opt.dataset.ip ? opt.dataset.name + ', ' + opt.dataset.ip : opt.dataset.name;
    panel.querySelector('.dot').classList.toggle('on', !!opt.dataset.ip);
    if (focus) opt.focus();
  }
  opts.forEach(function (opt, i) {
    opt.tabIndex = opt.getAttribute('aria-checked') === 'true' ? 0 : -1;
    opt.addEventListener('click', function () { pick(opt); });
    opt.addEventListener('keydown', function (e) {
      const step = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      pick(opts[(i + step + opts.length) % opts.length], true);
    });
  });

  demo.querySelectorAll('.switch').forEach(function (sw) {
    paint(sw);
    sw.addEventListener('click', function () {
      const on = sw.getAttribute('aria-checked') !== 'true';
      sw.setAttribute('aria-checked', String(on));
      paint(sw);
      if (sw === strategySw) showAccess(on);
    });
  });
})();

// Кнопка скачивания ведёт на последний релиз и показывает его версию и размер.
// Нет сети или релиза — остаётся ссылка на страницу Releases.
(function () {
  const btn = document.getElementById('dl');
  const note = document.getElementById('dl-note');
  if (!btn || !note || !window.fetch) return;

  fetch('https://api.github.com/repos/emptyenemy/chimera/releases/latest', { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (rel) {
      const asset = (rel.assets || []).find(function (a) { return /^Chimera-.+-win64\.zip$/.test(a.name); });
      if (!asset) return;
      const version = String(rel.tag_name || '').replace(/^v/, '');
      const mb = Math.round(asset.size / 1048576);
      btn.href = asset.browser_download_url;
      note.textContent = 'Версия ' + version + ', ' + mb + ' МБ. Windows 10 и 11. Python и git не нужны: распаковали архив и запустили.';
    })
    .catch(function () {});
})();
