(async () => {
  const steps = [];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(50); } throw new Error(message); };
  let viewportId = 0;
  const resize = async width => {
    const id = ++viewportId;
    __smokeViewport(JSON.stringify({ id, width, height: 820 }));
    await wait(() => window.__SMOKE_VIEWPORT_DONE__ === id, 'Viewport change failed');
    await sleep(80);
  };
  const go = async page => {
    Pages.go(page);
    await wait(() => el(`page-${page}`)?.querySelector('[data-slot="card"]'), `${page} not loaded`);
    await sleep(180);
  };
  const scan = name => {
    const page = document.querySelector('[data-page]');
    const failures = [];
    for (const node of page.querySelectorAll('button, input, textarea, [role="switch"], [role="combobox"]')) {
      const r = node.getBoundingClientRect();
      if (!r.width || !r.height || (r.width <= 1 && r.height <= 1) || node.closest('[data-slot="table-container"]')) continue;
      const card = node.closest('[data-slot="card"]') ?? page;
      const bounds = card.getBoundingClientRect();
      if (r.left < bounds.left - 2 || r.right > bounds.right + 2 || r.right > innerWidth + 2)
        failures.push({ id: node.dataset.testid ?? node.id ?? node.tagName, width: Math.round(r.width), excess: Math.round(r.right - Math.min(bounds.right, innerWidth)) });
    }
    steps.push({ name, ok: failures.length === 0, ...(failures.length ? { clipped: failures } : {}) });
  };
  try {
    for (const language of ['ru', 'en']) {
      await resize(1280);
      await go('settings'); el('settings-tab-general').click(); await sleep(80);
      await wait(() => el(`settings-lang-${language}`), 'Language selector missing');
      el(`settings-lang-${language}`).click();
      await wait(() => el(`settings-lang-${language}`).getAttribute('aria-pressed') === 'true' && !el(`settings-lang-${language}`).disabled, 'Language did not change');
      await wait(() => Pages.list.find(page => page.id === 'settings').title === (language === 'en' ? 'Settings' : 'Настройки'), 'Catalog language did not change');
      for (const [width, sidebar] of [[1280, 232], [860, 232], [860, 360], [480, 232], [360, 232]]) {
        await resize(width);
        const resizer = el('sidebar-resize');
        resizer.dispatchEvent(sidebar === 360
          ? new KeyboardEvent('keydown', { key: 'End', bubbles: true })
          : new MouseEvent('dblclick', { bubbles: true }));
        await wait(() => resizer.getAttribute('aria-valuenow') === String(sidebar), 'Sidebar width did not change');
        await sleep(220);
        for (const page of Pages.list.map(page => page.id)) {
          await go(page);
          scan(`${language} ${width}px sidebar ${sidebar} ${page}`);
          if (page === 'hosts') {
            el('hosts-advanced-toggle').click(); await sleep(100);
            scan(`${language} ${width}px sidebar ${sidebar} hosts advanced`);
            const interval = el('hosts-refresh-interval');
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(interval, '12abc');
            interval.dispatchEvent(new Event('input', { bubbles: true })); await sleep(20);
            interval.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
            await wait(() => el('hosts-refresh-interval-error'), 'Hosts interval error missing');
            scan(`${language} ${width}px sidebar ${sidebar} hosts interval error`);
            interval.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          }
          if (page === 'telegram') {
            el('tg-advanced-toggle').click(); await sleep(100);
            scan(`${language} ${width}px sidebar ${sidebar} telegram advanced`);
          }
          if (page === 'settings') {
            for (const tab of ['general', 'updates', 'tools']) {
              el(`settings-tab-${tab}`).click(); await sleep(100);
              scan(`${language} ${width}px sidebar ${sidebar} settings ${tab}`);
            }
          }
        }
      }
    }
    await go('telegram');
    const main = el('main');
    const heading = document.querySelector('[data-page] h1');
    const top = heading.getBoundingClientRect().top;
    steps.push({ name: 'Navigation opens at top', ok: main.scrollTop === 0 && top >= 0, scroll: main.scrollTop, documentScroll: document.scrollingElement.scrollTop, headingTop: top });
  } catch (error) {
    steps.push({ name: String(error), ok: false });
  }
  return JSON.stringify(steps);
})()
