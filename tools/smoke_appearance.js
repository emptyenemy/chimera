(async () => {
  const steps = [];
  const need = (value, message) => { if (!value) throw new Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(100); } throw new Error(message); };
  const click = async id => { await wait(() => el(id) && !el(id).disabled, `${id} not ready`); el(id).click(); await sleep(150); };
  const input = (id, value) => { const node = el(id); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new Event('input', { bubbles: true })); };
  const style = key => document.documentElement.style.getPropertyValue(key);
  const palette = async id => { await click('appearance-palette'); await click(`appearance-palette-${id}`); await wait(() => document.documentElement.dataset.palette === id, `Palette ${id} not applied`); };
  const api = async (method, ...args) => JSON.parse(await Bridge.call(method, JSON.stringify(args)));
  try {
    need(window.__CHIMERA_APPEARANCE__?.palette === 'dracula', 'Startup palette missing');
    need(style('--background') === '#282a36', 'Startup background differs from boot');
    need(window.__SMOKE_FIRST_FRAME__?.palette === 'dracula' && window.__SMOKE_FIRST_FRAME__?.background === '#282a36', 'Wrong palette at first rendered frame');
    steps.push({ name: 'Saved whole palette applied before React', ok: true });
    Pages.go('settings');
    await wait(() => el('appearance-palette'), 'Appearance card missing');
    for (const id of ['github-light', 'catppuccin-mocha', 'nord', 'tokyo-night', 'one-dark', 'gruvbox', 'solarized-dark', 'dracula']) await palette(id);
    steps.push({ name: 'Whole palettes change on the live page', ok: true });
    const bg = style('--background');
    await click('appearance-accent-blue');
    await wait(() => style('--primary') !== window.__CHIMERA_APPEARANCE__.accent, 'Preset accent unchanged');
    need(style('--background') === bg, 'Accent changed a surface');
    await click('settings-theme-system');
    input('appearance-color', '#00ff00'); await sleep(100); await click('appearance-check');
    await wait(() => el('appearance-normalized'), 'Clamping notice missing');
    await sleep(1700);
    need(el('appearance-normalized'), 'System poll discarded the color preview');
    need(style('--primary') !== '#00ff00', 'Acid color displayed unchanged');
    input('appearance-color', '#010101'); await sleep(100); await click('appearance-check');
    await wait(() => el('appearance-contrast-warning'), 'Contrast warning missing');
    await click('appearance-accept');
    await wait(() => !el('appearance-contrast-warning'), 'Safe accent not accepted');
    const readable = (await api('appearance_state')).data;
    need(readable.contrast.text >= 4.5 && readable.contrast.background >= 4.5, 'Unsafe contrast accepted');
    steps.push({ name: 'Accent presets, normalization, warning and safe alternative', ok: true });
    await click('appearance-radius-rounded'); await click('appearance-density-compact');
    await wait(() => style('--radius') === '1rem' && style('--spacing') === '0.22rem', 'Shape settings not applied');
    input('appearance-name', 'My checked theme'); await sleep(100); await click('appearance-save');
    await wait(() => el('appearance-palette').textContent.includes('My checked theme'), 'Own theme not selected');
    const ownAccent = style('--primary');
    await palette('nord');
    await click('appearance-palette'); await click('appearance-palette-personal');
    await wait(() => style('--primary') === ownAccent && style('--radius') === '1rem', 'Own theme not restored');
    steps.push({ name: 'Own theme survives selection of another preset', ok: true });
    await click('settings-theme-system');
    await api("__smoke_system_theme", "light"); window.__smokeSystemMode('light');
    await wait(() => document.documentElement.dataset.theme === 'light', 'System light mode not followed');
    need(style('--background') !== bg, 'System mode did not replace the whole palette');
    await api("__smoke_system_theme", "dark"); window.__smokeSystemMode('dark');
    await wait(() => document.documentElement.dataset.theme === 'dark', 'System dark mode not followed');
    await click('appearance-windows');
    await wait(() => el('appearance-color').disabled, 'Windows accent control did not apply');
    await click('appearance-windows');
    steps.push({ name: 'System light/dark and Windows accent follow without reload', ok: true });
    await click('appearance-refresh');
    await click('appearance-palette');
    await wait(() => el('appearance-palette-catalog-check'), 'GitHub catalog theme missing');
    await click('appearance-palette-catalog-check');
    await wait(() => document.documentElement.dataset.palette === 'catalog-check', 'Downloaded palette not applied');
    steps.push({ name: 'Catalog refresh offers a new validated theme', ok: true });
    await palette('catppuccin-mocha');
    await click('appearance-accent-violet');
    const slider = el('appearance-hue').querySelector('input[type=range]');
    need(slider, 'Hue slider missing');
    const beforeHue = (await api('appearance_state')).data.settings.appearance.accent;
    slider.focus();
    window.__smokeKey('ArrowRight');
    await wait(async () => (await api('appearance_state')).data.settings.appearance.accent !== beforeHue, 'Hue keyboard change not saved');
    steps.push({ name: 'Hue slider preview and committed keyboard change', ok: true });
    el('appearance-hue').scrollIntoView({ block: 'center' });
    await sleep(100);
    const realCall = Bridge.call;
    let activePreviews = 0, maxPreviews = 0, previews = 0, saves = 0;
    Bridge.call = async (method, args) => {
      if (method === 'appearance_apply') saves++;
      if (method !== 'appearance_preview') return realCall(method, args);
      previews++; maxPreviews = Math.max(maxPreviews, ++activePreviews);
      try { await sleep(180); return await realCall(method, args); }
      finally { activePreviews--; }
    };
    let pointerId = 0;
    const mouse = async (type, x, y, extra = {}) => {
      const id = ++pointerId;
      window.__smokePointer(JSON.stringify({ id, type, x, y, ...extra }));
      for (let i = 0; i < 200 && window.__SMOKE_POINTER_DONE__ !== id; i++) await sleep(5);
      need(window.__SMOKE_POINTER_DONE__ === id, 'Pointer event did not complete');
    };
    try {
      const track = el('appearance-hue').querySelector('[data-slot=slider-track]').getBoundingClientRect();
      const y = track.top + track.height / 2;
      const persistedBeforeDrag = (await api('appearance_state')).data.settings.appearance.accent;
      await mouse('mousePressed', track.left + track.width * .1, y, { buttons: 1, clickCount: 1 });
      for (let i = 1; i <= 30; i++) {
        const fraction = .1 + .75 * i / 30;
        await mouse('mouseMoved', track.left + track.width * fraction, y, { buttons: 1 });
        const shown = Number(el('appearance-hue').querySelector('input[type=range]').value);
        need(Math.abs(shown - fraction * 359) < 3, `Hue thumb lags: ${shown}, expected ${fraction * 359}`);
      }
      need(saves === 0, 'Dragging persisted intermediate hues');
      need((await api('appearance_state')).data.settings.appearance.accent === persistedBeforeDrag, 'Preview wrote configuration');
      const finalHue = Number(el('appearance-hue').querySelector('input[type=range]').value);
      await mouse('mouseReleased', track.left + track.width * .85, y, { buttons: 0, clickCount: 1 });
      await wait(async () => {
        const saved = (await api('appearance_state')).data;
        return Math.abs(saved.hue - finalHue) <= 1 && !el('appearance-hue').querySelector('input').disabled;
      }, 'Final pointer hue not saved');
      const savedColor = style('--primary');
      await wait(() => activePreviews === 0, 'Preview requests did not finish');
      await sleep(200);
      need(style('--primary') === savedColor, 'Late preview overrode committed hue');
      need(maxPreviews === 1 && previews < 15, `Preview flood: ${previews} requests, ${maxPreviews} concurrent`);
      need(saves === 1, `Expected one final save, got ${saves}`);
      steps.push({ name: 'Pointer drag stays responsive with a slow bridge; one final save', ok: true, previews, maxPreviews });
    } finally { Bridge.call = realCall; }
    input('appearance-color', '#cf5288'); await sleep(100); await click('appearance-check');
    const savedAccent = (await api('appearance_state')).data.accent;
    await wait(() => style('--primary') !== savedAccent, 'Color preview missing');
    Pages.go('dashboard');
    await wait(() => style('--primary') === savedAccent, 'Leaving appearance retained an unsaved preview');
    Pages.go('settings');
    await wait(() => el('settings-theme'), 'Settings did not return after preview');
    steps.push({ name: 'Leaving appearance restores the saved palette', ok: true });
    el('settings-theme').scrollIntoView({ block: 'start' });
    const persisted = (await api('appearance_state')).data;
    need(persisted.settings.appearance_custom?.appearance.name === 'My checked theme', 'Own theme not persisted');
    steps.push({ name: 'Saved appearance remains readable and own variant persists', ok: true });
    for (const page of Pages.list) {
      Pages.go(page.id);
      await wait(() => document.querySelector(`[data-page="${page.id}"]`) && !document.querySelector(`[data-page="${page.id}"] [data-slot="skeleton"]`), `Page ${page.id} did not load`);
    }
    Pages.go('settings');
    await wait(() => el('settings-theme'), 'Settings missing after navigation');
    steps.push({ name: 'All nine lazy routes open and return without reload', ok: true });
    return JSON.stringify(steps);
  } catch (error) {
    return JSON.stringify([...steps, { name: 'Appearance UI failure', ok: false, detail: error.stack, body: document.body.innerText.slice(-4000) }]);
  }
})()
