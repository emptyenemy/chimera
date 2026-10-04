(async () => {
  const steps = [];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const need = (value, message) => { if (!value) throw new Error(message); };
  const wait = async (fn, message) => { for (let i = 0; i < 150; i++) { if (await fn()) return; await sleep(75); } throw new Error(message); };
  const click = async id => { await wait(() => el(id) && !el(id).disabled, `${id} not ready`); el(id).click(); await sleep(60); };
  const input = value => {
    const node = el('checks-input');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value);
    // inputType как у набора с клавиатуры: ввод без него Base UI считает автозаполнением и подсказок не открывает
    node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
  };
  const api = async (method, ...args) => {
    const reply = JSON.parse(await Bridge.call(method, JSON.stringify(args)));
    if (!reply.ok) throw new Error(reply.error);
    return reply.data;
  };
  const realCall = Bridge.call;
  try {
    Pages.go('checks');
    await wait(() => el('checks-run') && el('checks-input'), 'Checks page not loaded');
    input('.broken..example, ftp://example.com'); await sleep(50); await click('checks-run');
    need((await api('__smoke_checks', 'state')).manual.length === 0, 'Invalid input reached the checker');
    steps.push({ name: 'Malformed targets do not start network checks', ok: true });

    let releaseManual;
    const manualGate = new Promise(resolve => { releaseManual = resolve; });
    Bridge.call = async (method, args) => {
      const reply = await realCall(method, args);
      if (method === 'block_check_one' || method === 'chebur_check_one') await manualGate;
      return reply;
    };
    input('https://пример.рф/path 1.1.1.1 https://[2606:4700:4700::1111]/ www.example.com');
    await sleep(50); await click('checks-run');
    await api('__smoke_checks', 'foreign'); await sleep(150);
    need(!el('checks-row-foreign.example') && el('checks-run').disabled, 'Foreign events changed the manual run');
    Bridge.call = realCall; releaseManual();
    await wait(() => !el('checks-run').disabled, 'Manual checks did not finish');
    for (const host of ['xn--e1afmkfd.xn--p1ai', '1.1.1.1', '2606:4700:4700::1111', 'example.com'])
      need(el(`checks-row-${host}`)?.dataset.tone === 'success', `Manual target ${host} missing`);
    steps.push({ name: 'International domains, URLs and IPv4/IPv6 work; foreign streams are ignored', ok: true });

    await api('__smoke_checks', 'hold');
    el('checks-input').focus(); input('bulk');
    await wait(() => el('checks-suggest-list-bulk'), 'Search did not suggest the list');
    el('checks-suggest-list-bulk').click(); await sleep(60);
    await wait(async () => { const s = await api('__smoke_checks', 'state'); return s.finished.block && s.finished.rkn; }, 'Bulk workers did not finish');
    const state = await api('__smoke_checks', 'state');
    need(state.block === 1100 && state.rkn === 1100 && state.events > 2200, 'Bulk snapshot or event overflow not exercised');
    Pages.go('dashboard'); await sleep(150);
    await api('__smoke_checks', 'release'); await sleep(300);
    Pages.go('checks');
    await wait(() => el('checks-run') && !el('checks-run').disabled && el('checks-row-site-1099.example'), 'Complete bulk results not recovered');
    need(document.querySelectorAll('[data-testid^="checks-row-"]').length === 1100, 'Bulk check lost results');
    need(!el('checks-row-changed-only.example'), 'Registry checked a newer list instead of the original snapshot');
    need(el('checks-row-site-1.example').dataset.tone === 'warning', 'DNS failure result lost');
    need(!el('checks-row-site-1.example').querySelector('[data-slot="spinner"]'), 'Finished row is still pending');
    steps.push({ name: 'All 1100 results survive event overflow, a changed list and navigation', ok: true });
    await click('checks-only-problems');
    need(document.querySelectorAll('[data-testid^="checks-row-"]').length === 1 && el('checks-row-site-1.example'), 'Problem filter lost the restored DNS failure');
    steps.push({ name: 'Problem filter and final summary work after recovery', ok: true });
  } catch (error) {
    steps.push({ name: String(error), ok: false });
  } finally {
    Bridge.call = realCall;
    await api('__smoke_checks', 'release');
  }
  return JSON.stringify(steps);
})()
