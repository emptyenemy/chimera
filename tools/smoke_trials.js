(async () => {
  const steps = [];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const need = (condition, message) => { if (!condition) throw new Error(message); };
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(100); } throw new Error(message); };
  // Switch и Checkbox из Base UI — span: заблокированность у них в data-disabled, а не в .disabled
  const ready = id => el(id) && !el(id).matches(':disabled, [data-disabled], [aria-disabled=true]');
  const click = async id => { await wait(() => ready(id), `${id} not ready`); el(id).click(); await sleep(150); };
  const input = (id, value) => { const node = el(id); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new Event('input', { bubbles: true })); };
  const call = async (method, ...args) => JSON.parse(await Bridge.call(method, JSON.stringify(args)));
  const state = async () => (await call('__smoke_trial', 'state')).data;
  async function start(page, kind) {
    Pages.go(page);
    await click(`trial-open-${kind}`);
    await wait(() => el('trial-dialog'), 'Trial dialog missing');
    await click('trial-start');
    await wait(() => el('trial-banner') && !el('trial-dialog'), 'Trial banner missing');
  }
  async function revert() {
    await click('trial-revert');
    await wait(async () => !(await state()).trial.active, 'Trial not reverted');
    await click('trial-dismiss');
  }
  try {
    await start('strategies', 'strategy');
    need(el('trial-keep').disabled, 'Confirmation available before checks');
    need(el('strat-toggle').matches(':disabled'), 'Normal mutations enabled during trial');
    Pages.go('dashboard'); await sleep(200);
    need(!el('dashboard-panic').matches(':disabled'), 'Emergency shutdown disabled during trial');
    need(el('module-toggle-winws').matches(':disabled, [data-disabled], [aria-disabled=true]'), 'Dashboard toggle enabled during trial');
    Pages.go('strategies'); await sleep(200);
    await call('__smoke_trial', 'checks');
    await click('trial-keep');
    await wait(async () => !(await state()).trial.active, 'Confirmation did not finish trial');
    need((await state()).winws.running, 'Confirmation stopped the strategy');
    await click('trial-dismiss');
    steps.push({ name: 'Strategy trial: dialog, checks, disabled controls and confirmation', ok: true });

    await start('proxy', 'tun');
    need((await state()).proxy_mode === 'tun', 'TUN trial did not change mode');
    await revert();
    need((await state()).proxy_mode === 'pac', 'TUN rollback did not restore PAC');
    steps.push({ name: 'TUN trial restores the previous mode', ok: true });

    await start('hosts', 'hosts');
    need((await state()).hosts.applied, 'Hosts trial did not apply');
    await call('__smoke_trial', 'fail_checks');
    await wait(async () => !(await state()).trial.active, 'Failed checks did not revert');
    need(!(await state()).hosts.applied, 'Hosts remained applied after failed checks');
    await click('trial-dismiss');
    steps.push({ name: 'Failed control checks automatically restore hosts', ok: true });

    Pages.go('proxy'); await click('trial-open-tun');
    input('trial-seconds', '10'); await sleep(100);
    need(el('trial-start').disabled, 'Invalid duration is accepted');
    input('trial-seconds', '15'); await sleep(100);
    await click('trial-start');
    await call('__smoke_trial', 'expire');
    await wait(async () => !(await state()).trial.active, 'Timer did not revert');
    need((await state()).proxy_mode === 'pac', 'Timer did not restore original mode');
    await click('trial-dismiss');
    steps.push({ name: 'Duration validation and timeout without confirmation', ok: true });

    Pages.go('strategies');
    await click('trial-open-strategy');
    need(el('trial-dialog').querySelector('[data-slot=dialog-title]'), 'Dialog has no accessible title');
    return JSON.stringify(steps);
  } catch (error) {
    steps.push({ name: 'Trial UI scenario', ok: false, detail: String(error?.message || error) });
    return JSON.stringify(steps);
  }
})();
