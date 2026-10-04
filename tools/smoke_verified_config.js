(async () => {
  const steps = [];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const need = (condition, message) => { if (!condition) throw new Error(message); };
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(100); } throw new Error(message); };
  // Switch и Checkbox из Base UI — span: заблокированность у них в data-disabled, а не в .disabled
  const ready = id => el(id) && !el(id).matches(':disabled, [data-disabled], [aria-disabled=true]');
  const click = async id => { await wait(() => ready(id), `${id} not ready`); el(id).click(); await sleep(100); };
  const input = value => { const node = el('verified-domains'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new Event('input', { bubbles: true })); };
  const call = async (method, ...args) => JSON.parse(await Bridge.call(method, JSON.stringify(args)));
  try {
    const originalCall = Bridge.call;
    let releaseRead;
    const readGate = new Promise(resolve => { releaseRead = resolve; });
    let heldReads = 0;
    Bridge.call = async (method, args) => {
      const reply = await originalCall(method, args);
      if (method === 'config_verified') {
        heldReads++;
        await readGate;
      }
      return reply;
    };
    Pages.go('settings');
    await click('settings-tab-tools');
    await wait(() => el('verified-restore'), 'Verified section missing');
    need(el('verified-restore').disabled, 'Restore enabled without verified snapshot');
    await click('verified-open');
    input('https://youtube.com'); await sleep(100);
    need(el('verified-save').disabled, 'URL accepted instead of domain');
    input('youtube.com, discord.com'); await sleep(100);
    need(el('verified-dialog').querySelector('[data-slot=dialog-title]'), 'Dialog has no title');
    await click('verified-save');
    await wait(() => !el('verified-dialog') && !el('verified-restore').disabled, 'Successful check did not save');
    need(heldReads > 0, 'Initial verified-state read was not delayed');
    Bridge.call = originalCall;
    releaseRead();
    await sleep(200);
    need(!el('verified-restore').disabled && el('verified-summary').textContent.includes('discord.com'), 'Late initial read erased newly verified snapshot');
    steps.push({ name: 'Late initial state cannot erase a newly saved snapshot', ok: true });
    const first = (await call('config_verified')).data.backup;
    need(first.checks.length === 2 && el('verified-summary').textContent.includes('discord.com'), 'Checked sites missing');
    steps.push({ name: 'Input validation, successful checks and verified snapshot', ok: true });

    await call('__smoke_verified', 'fail');
    await click('verified-open');
    await click('verified-save');
    await wait(() => el('verified-error'), 'Failed checks not displayed');
    need(el('verified-checks').textContent.includes('Не открывается'), 'Per-site failures missing');
    need((await call('config_verified')).data.backup.id === first.id, 'Failure replaced working snapshot');
    el('verified-dialog').querySelector('[data-slot=dialog-close]').click();
    await wait(() => !el('verified-dialog'), 'Could not close failed check');
    steps.push({ name: 'Failed checks preserve previous snapshot and show every result', ok: true });

    await call('__smoke_verified', 'change');
    await click('verified-restore');
    await wait(() => el('backup-restore') && !el('backup-restore').disabled, 'Restore preview missing');
    need((await call('__smoke_verified', 'state')).data.mode === 'split', 'Preview applied changes prematurely');
    need(el('backup-preview-proxy'), 'Proxy changes not previewed');
    await click('backup-restore');
    await wait(() => !el('backups-dialog'), 'Restore did not finish');
    need((await call('__smoke_verified', 'state')).data.mode === 'pac', 'Working proxy mode not restored');
    need((await call('config_backups')).data.some(b => b.kind === 'restore'), 'Current state not backed up');
    steps.push({ name: 'Restore opens preview, requires a click and saves inverse snapshot', ok: true });

    await click('settings-backups-open');
    await wait(() => el('backup-select'), 'Backup history missing');
    need(document.body.textContent.includes('Проверенный'), 'Verified snapshot badge missing');
    el('backups-dialog').querySelector('[data-slot=dialog-close]').click();
    await sleep(100);
    steps.push({ name: 'Verified snapshot visible in backup history', ok: true });
  } catch (error) {
    steps.push({ name: error.message, ok: false });
  }
  return JSON.stringify(steps);
})()
