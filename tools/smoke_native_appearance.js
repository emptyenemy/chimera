(async () => {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const need = (condition, message) => { if (!condition) throw Error(message); };
  for (let i = 0; i < 300 && !document.body?.classList.contains('ready'); i++) await sleep(100);
  need(document.body.classList.contains('ready'), 'Native interface did not load');
  need(typeof api === 'function' && window.pywebview?.api, 'Native bridge unavailable');
  need(!window.__CHIMERA_HTTP__, 'Native window uses wrong bridge');
  need(document.documentElement.dataset.palette === 'dracula', 'Boot palette missing');
  const original = await api('appearance_state');
  const applied = await api('appearance_apply', { theme: 'light', appearance: { palette: 'github-light', accent_source: 'custom', accent: '#00ff00' } });
  need(applied.normalized && applied.contrast.text >= 4.5, 'Unsafe native accent');
  for (let i = 0; i < 100 && document.documentElement.dataset.palette !== 'github-light'; i++) await sleep(100);
  need(document.documentElement.dataset.palette === 'github-light', 'Native palette did not update');
  need(!document.documentElement.classList.contains('dark'), 'Native light mode did not update');
  await api('appearance_apply', original.settings);
  return JSON.stringify([{ name: 'Native WebView2: authenticated boot, bridge, palette and accent', ok: true, detail: 'Dracula → GitHub Light' }]);
})()
