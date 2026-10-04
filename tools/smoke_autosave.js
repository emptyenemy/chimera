(async () => {
  const steps = [];
  const need = (value, message) => { if (!value) throw new Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(50); } throw new Error(message); };
  // Switch и Checkbox из Base UI — span: заблокированность у них в data-disabled, а не в .disabled
  const ready = id => el(id) && !el(id).matches(':disabled, [data-disabled], [aria-disabled=true]');
  const click = async id => { await wait(() => ready(id), `${id} not ready`); el(id).click(); await sleep(60); };
  const input = (id, value) => {
    const node = el(id);
    const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const api = async (method, ...args) => {
    const result = JSON.parse(await Bridge.call(method, JSON.stringify(args)));
    if (!result.ok) throw new Error(result.error);
    return result.data;
  };
  const go = async (page, id) => { Pages.go(page); await wait(() => el(id), `${page} missing`); };
  const realCall = Bridge.call;
  try {
    await go('settings', 'settings-auto-elevate');
    Bridge.call = async (method, args) => {
      const reply = await realCall(method, args);
      if (method === 'config_set') await sleep(220);
      return reply;
    };
    await click('settings-auto-elevate'); await click('settings-close-to-tray');
    need(el('settings-auto-elevate').getAttribute('aria-checked') === 'true', 'First optimistic setting lost');
    need(el('settings-close-to-tray').getAttribute('aria-checked') === 'true', 'Second optimistic setting lost');
    await wait(async () => { const cfg = await api('config_read'); return cfg.auto_elevate && cfg.close_to_tray; }, 'Concurrent settings not saved');
    await sleep(350);
    need(el('settings-close-to-tray').getAttribute('aria-checked') === 'true', 'Late reply reverted setting');
    Bridge.call = realCall;
    steps.push({ name: 'Two quick settings survive delayed replies', ok: true });
    await click('settings-tab-updates');
    await wait(() => el('settings-src-Source A'), 'Fixture sources missing');
    await click('settings-src-check-all');
    await wait(() => el('settings-src-update-Source A'), 'Streamed source result missing');
    Pages.go('dashboard'); await sleep(100);
    await go('settings', 'settings-src-check-all');
    need(el('settings-src-check-all').disabled, 'Returning to settings unlocked the active bulk check');
    need((await api('__smoke_sources', 'state')).checks === 1, 'Returning started another bulk check');
    await click('settings-src-update-Source A'); await click('confirm-ok');
    await wait(async () => (await api('__smoke_sources', 'state')).updates === 1, 'Source update not started');
    await api('__smoke_sources', 'release-check');
    await wait(() => !el('settings-src-check-all').disabled, 'Bulk check did not finish');
    need(el('settings-src-check-Source A').disabled && el('settings-src-Source A').textContent.includes('обновление'), 'Bulk check cleared another operation');
    await api('__smoke_sources', 'release-update');
    await wait(() => !el('settings-src-check-Source A').disabled, 'Source update did not finish');
    need(el('settings-src-Source A').textContent.includes('2'), 'New source version missing');
    steps.push({ name: 'Bulk source checks survive navigation and preserve concurrent row updates', ok: true });

    await go('telegram', 'tg-port');
    input('tg-port', '19444');
    await sleep(20);
    Pages.go('dashboard');
    await wait(async () => (await api('tg_state')).port === 19444, 'Leaving Telegram lost connection draft');
    steps.push({ name: 'Leaving Telegram flushes connection draft', ok: true });
    await go('telegram', 'tg-port');
    await click('tg-advanced-toggle');
    await wait(() => el('tg-adv-fake-tls'), 'Advanced input missing');
    input('tg-adv-fake-tls', 'tls.example');
    await sleep(20); Pages.go('dashboard');
    await wait(async () => (await api('tg_state')).fake_tls_domain === 'tls.example', 'Leaving Telegram lost advanced draft');
    steps.push({ name: 'Leaving Telegram flushes advanced draft', ok: true });

    await go('telegram', 'tg-port');
    Bridge.call = async (method, args) => { if (method === 'tg_set_config') await sleep(250); return realCall(method, args); };
    input('tg-port', '99999');
    await sleep(20);
    el('tg-port').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    await sleep(30); await click('tg-autostart');
    await wait(async () => (await api('tg_state')).autostart, 'Autostart not saved');
    need((await api('tg_state')).port === 19444, 'Autostart overwrote port');
    Bridge.call = realCall;
    steps.push({ name: 'Failed port save does not poison queued Telegram autostart', ok: true });
    let fractionalReplies = 0;
    Bridge.call = async (method, args) => {
      const response = await realCall(method, args);
      if (method === 'tg_set_config') fractionalReplies++;
      return response;
    };
    input('tg-port', '19444.5'); await sleep(20);
    el('tg-port').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    await wait(() => fractionalReplies > 0, 'Fractional port was not checked');
    await sleep(80);
    need((await api('tg_state')).port === 19444, 'Fractional Telegram port was silently truncated');
    need(el('tg-port').value === '19444.5', 'Rejected port draft was lost');
    input('tg-port', '19444'); await sleep(20);
    el('tg-port').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    await wait(() => fractionalReplies > 1, 'Corrected port was not saved');
    Bridge.call = realCall;
    steps.push({ name: 'Fractional Telegram ports are rejected without replacing saved settings or losing the draft', ok: true });

    await go('hosts', 'hosts-advanced-toggle'); await click('hosts-advanced-toggle');
    await wait(() => el('hosts-refresh-interval'), 'Hosts interval fields missing');
    const blurInterval = id => el(id).dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    let backgroundWrites = 0;
    Bridge.call = async (method, args) => {
      if (method === 'hosts_set_background') backgroundWrites++;
      return realCall(method, args);
    };
    const originalBackground = (await api('hosts_state')).background;
    for (const invalid of ['12abc', '1.5', '0', '99999999999999999999999']) {
      input('hosts-refresh-interval', invalid); await sleep(20); blurInterval('hosts-refresh-interval');
      await wait(() => el('hosts-refresh-interval-error'), 'Invalid interval has no error');
      need(el('hosts-refresh-interval').value === invalid && el('hosts-refresh-interval').getAttribute('aria-invalid') === 'true', 'Invalid interval was replaced');
    }
    need(backgroundWrites === 0, 'Invalid interval reached the backend');
    need((await api('hosts_state')).background.refresh_interval === originalBackground.refresh_interval, 'Invalid interval changed saved settings');
    el('hosts-refresh-interval').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(() => !el('hosts-refresh-interval-error'), 'Escape did not clear interval error');
    need(el('hosts-refresh-interval').value === String(originalBackground.refresh_interval / 3600), 'Escape did not restore saved interval');
    steps.push({ name: 'Invalid Hosts intervals remain editable and never reach the backend', ok: true });

    input('hosts-refresh-interval', '8'); await sleep(20); blurInterval('hosts-refresh-interval');
    await wait(async () => (await api('hosts_state')).background.refresh_interval === 28800, 'Hours were not converted to seconds');
    await sleep(80); blurInterval('hosts-refresh-interval'); await sleep(80);
    need(backgroundWrites === 1, 'Untouched blur duplicated an interval write');
    steps.push({ name: 'Hosts intervals save correct units without duplicate blur writes', ok: true });

    Bridge.call = async (method, args) => {
      if (method === 'hosts_set_background' && ++backgroundWrites === 2)
        return JSON.stringify({ ok: false, error: 'Simulated interval write failure' });
      return realCall(method, args);
    };
    input('hosts-refresh-interval', '2'); await sleep(20); blurInterval('hosts-refresh-interval');
    await wait(() => el('hosts-refresh-interval-error'), 'Failed interval save has no error');
    need(el('hosts-refresh-interval').value === '2', 'Failed interval draft was lost');
    need((await api('hosts_state')).background.refresh_interval === 28800, 'Failed write changed saved interval');
    blurInterval('hosts-refresh-interval');
    await wait(async () => (await api('hosts_state')).background.refresh_interval === 7200, 'Failed interval retry did not save');
    await wait(() => !el('hosts-refresh-interval-error'), 'Successful interval retry retained error');
    steps.push({ name: 'Failed Hosts interval saves retain their draft and can be retried', ok: true });

    Bridge.call = async (method, args) => {
      if (method === 'hosts_set_background') await sleep(220);
      return realCall(method, args);
    };
    input('hosts-check-interval', '3'); await sleep(20); blurInterval('hosts-check-interval');
    input('hosts-check-interval', '4'); await sleep(20);
    input('hosts-refresh-interval', '5'); await sleep(20); blurInterval('hosts-refresh-interval');
    await wait(async () => (await api('hosts_state')).background.refresh_interval === 18000, 'Queued Hosts settings did not save');
    need(el('hosts-check-interval').value === '4', 'An older interval reply cleared a newer draft');
    blurInterval('hosts-check-interval');
    await wait(async () => (await api('hosts_state')).background.check_interval === 240, 'Latest minutes draft not saved');
    input('hosts-refresh-interval', ''); await sleep(20); blurInterval('hosts-refresh-interval');
    await wait(async () => (await api('hosts_state')).background.refresh_interval === 21600, 'Blank interval did not restore default');
    Bridge.call = realCall;
    steps.push({ name: 'Queued Hosts intervals preserve newer drafts and blank input restores the default', ok: true });

    await go('providers', 'providers-probe-settings-toggle'); await click('providers-probe-settings-toggle');
    await wait(() => el('dns-probe-error'), 'Probe read error not displayed');
    await click('dns-probe-retry'); await wait(() => el('dns-probe-bypass'), 'Probe read retry failed');
    steps.push({ name: 'DNS probe read failures offer a working retry', ok: true });
    let probeWrites = 0;
    Bridge.call = async (method, args) => {
      if (method === 'dns_set_probe_config') await sleep(++probeWrites === 1 ? 300 : 20);
      return realCall(method, args);
    };
    const blurProbe = id => el(id).dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    input('dns-probe-bypass', 'first.example'); await sleep(20); blurProbe('dns-probe-bypass');
    input('dns-probe-ad', 'next.example'); await sleep(20); blurProbe('dns-probe-ad');
    await wait(async () => (await api('dns_probe_config')).ad === 'next.example', 'Queued probe edits not saved');
    await sleep(350);
    const savedProbe = await api('dns_probe_config');
    need(savedProbe.bypass.includes('first.example') && savedProbe.ad === 'next.example', 'Older probe save replaced newer fields');
    need(probeWrites === 2, 'Probe blur duplicated a save');
    Bridge.call = realCall;
    input('dns-probe-ad', 'leave.example'); await sleep(20); Pages.go('dashboard');
    await wait(async () => (await api('dns_probe_config')).ad === 'leave.example', 'Leaving Providers lost pending probe edits');
    steps.push({ name: 'DNS probe writes serialize, deduplicate blur and flush on navigation', ok: true });
    await go('providers', 'providers-probe-settings-toggle'); await click('providers-probe-settings-toggle');
    await wait(() => el('dns-probe-bypass'), 'Probe editor not restored');
    input('dns-probe-bypass', 'recover.example'); await sleep(20); Pages.go('dashboard');
    await wait(async () => (await api('__smoke_probe_failures')) === 1, 'Failed probe save not exercised');
    await go('providers', 'providers-probe-settings-toggle'); await click('providers-probe-settings-toggle');
    await wait(() => el('dns-probe-error') && el('dns-probe-bypass')?.value === 'recover.example', 'Failed probe draft lost after navigation');
    await click('dns-probe-retry');
    await wait(() => !el('dns-probe-error'), 'Probe save retry failed');
    need((await api('dns_probe_config')).bypass.includes('recover.example'), 'Probe retry did not persist draft');
    steps.push({ name: 'Failed DNS probe drafts survive navigation and can be retried', ok: true });

    need(!el('nav-dot-dns'), 'DNS dot lit before the program changed DNS');
    await api('__smoke_dns_active', [7]); await api('hub_refresh', ['dnsStatus']);
    await wait(() => el('nav-dot-dns'), 'DNS dot did not light up after the program changed DNS');
    await api('__smoke_dns_active', []); await api('hub_refresh', ['dnsStatus']);
    await wait(() => !el('nav-dot-dns'), 'DNS dot stayed lit after DNS was reset');
    steps.push({ name: 'Sidebar DNS dot follows the DNS set by the program', ok: true });

    await go('settings', 'settings-tab-updates'); await click('settings-tab-updates');
    await click('settings-data-check');
    await wait(() => el('settings-data-plan')?.textContent.includes('Добавится: 1'), 'Data release preview missing');
    need(el('settings-data-kept')?.textContent.includes('lists/youtube.txt'), 'Own list edits are not shown as kept');
    await click('settings-data-install');
    await wait(() => el('settings-data-status')?.textContent.includes('Установлены последние'), 'Data update did not finish');
    steps.push({ name: 'Strategies and lists: preview keeps own edits, update installs the release', ok: true });

    await go('lists', 'lists-new');
    await wait(() => el('list-row-sample'), 'Sample list missing');
    el('lists-new').click(); el('lists-new').click();
    await wait(() => el('prompt-input'), 'First prompt missing');
    input('prompt-input', 'queue-a'); await sleep(20); await click('prompt-ok');
    await wait(() => el('prompt-input')?.value === '', 'Second identical prompt reused first value');
    input('prompt-input', 'queue-b'); await sleep(20); await click('prompt-ok');
    await wait(() => el('list-row-queue-b'), 'Second list not created');
    steps.push({ name: 'Queued identical prompts have independent input', ok: true });

    await click('list-row-sample'); await wait(() => el('lists-textarea'), 'Editor missing');
    input('lists-textarea', 'example.com\nlatest.example\n'); await sleep(20);
    await click('list-menu-sample'); await click('list-rename');
    input('prompt-input', 'renamed'); await sleep(20); await click('prompt-ok');
    await wait(() => el('lists-editor')?.dataset.list === 'renamed' && el('lists-textarea'), 'Renamed editor missing');
    need((await api('lists_read', 'renamed')).includes('latest.example'), 'Rename lost unsaved text');
    steps.push({ name: 'Rename preserves unsaved list text', ok: true });
    input('lists-textarea', 'delete.example\n'); await sleep(20);
    await click('list-menu-renamed'); await click('list-delete'); await click('confirm-ok');
    await wait(() => !el('list-row-renamed'), 'List not deleted');
    await sleep(700);
    need(!(await api('lists_all')).some(item => item.name === 'renamed' || item.name === 'sample'), 'Autosave recreated removed file');
    steps.push({ name: 'Delete cannot recreate list through cleanup autosave', ok: true });

    await click('list-row-queue-b'); await wait(() => el('lists-textarea'), 'Append editor missing');
    input('lists-textarea', 'draft.example\n'); await sleep(20);
    await click('lists-record'); await click('rec-start'); await click('rec-stop');
    await wait(() => el('rec-add'), 'Recorded result missing');
    await wait(() => el('rec-reach-recorded.example')?.dataset.tone === 'err' && el('rec-reach-open.example')?.dataset.tone === 'ok',
      'Recorded domains were not checked');
    await wait(() => el('rec-domain-recorded.example').getAttribute('aria-checked') === 'true'
      && el('rec-domain-open.example').getAttribute('aria-checked') === 'false', 'Blocked domain was not picked alone');
    await click('rec-target');
    const option = [...document.querySelectorAll('[role="option"]')].find(node => node.textContent.trim() === 'queue-b');
    need(option, 'Target list missing'); option.click(); await sleep(30);
    await click('rec-add');
    await wait(() => !el('rec-dialog'), 'Recording dialog not closed');
    const text = await api('lists_read', 'queue-b');
    need(text.includes('draft.example') && text.includes('recorded.example'), 'Appending recorded domains lost open draft');
    need(!text.includes('open.example'), 'A domain that opens was added without being picked');
    steps.push({ name: 'Recorded domains are checked, blocked ones picked, and merge with unsaved editor text', ok: true });
    Bridge.call = async (method, args) => {
      if (method === 'proxy_set_lists' || method === 'winws_set_lists') await sleep(200);
      return realCall(method, args);
    };
    for (const [page, prefix, method] of [['proxy', 'proxy', 'proxy_state'], ['strategies', 'strat', 'winws_state']]) {
      await go(page, `${prefix}-list-queue-a`);
      await click(`${prefix}-list-queue-a`); await click(`${prefix}-list-queue-b`);
      await wait(async () => (await api(method)).lists.includes('queue-b'), `${page} second list not saved`);
      need(!(await api(method)).lists.includes('queue-a'), `${page} repeated the failed list connection`);
      need(el(`${prefix}-list-queue-b`).getAttribute('aria-checked') === 'true', `${page} lost successful selection`);
      need(el(`${prefix}-list-queue-a`).getAttribute('aria-checked') === 'false', `${page} failed selection not rolled back`);
    }
    steps.push({ name: 'Proxy and strategy list selections survive queued failures', ok: true });
    await go('proxy', 'proxy-link');
    Bridge.call = async (method, args) => { if (method === 'proxy_set_link') await sleep(180); return realCall(method, args); };
    const blurLink = () => el('proxy-link').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    input('proxy-link', 'fixture-a'); await sleep(20); blurLink(); blurLink();
    await sleep(20); input('proxy-link', 'fixture-b'); await sleep(20); blurLink();
    await sleep(20); input('proxy-link', 'fixture-a'); await sleep(20); blurLink();
    await wait(async () => (await api('__smoke_link_count')) === 3, 'Link writes not coalesced correctly');
    await sleep(100);
    need((await api('proxy_state')).link === 'fixture-a', 'Reverting an in-flight link lost the final value');
    Pages.go('dashboard'); await sleep(250);
    need((await api('__smoke_link_count')) === 3, 'Leaving page repeated a confirmed link save');
    steps.push({ name: 'Proxy deduplicates blur saves and preserves the latest repeated value', ok: true });
    Bridge.call = realCall;
    await go('proxy', 'proxy-link');
    input('proxy-link', 'https://sub.example/s/token'); await sleep(20); blurLink();
    await wait(() => el('proxy-server-0') && el('proxy-server-1'), 'Subscription servers not listed');
    await wait(() => el('proxy-server-1').dataset.state === 'selected', 'Fastest server was not picked');
    need(el('proxy-link').value === 'https://sub.example/s/token', 'Link field lost the subscription address');
    await click('proxy-server-use-0');
    await wait(() => el('proxy-server-0').dataset.state === 'selected', 'Server choice not applied');
    await click('proxy-fastest');
    await wait(() => el('proxy-server-1').dataset.state === 'selected', 'Pick the fastest did not switch back');
    await click('proxy-sub-refresh');
    await wait(() => el('proxy-server-1')?.dataset.state === 'selected', 'Refresh lost the servers');
    steps.push({ name: 'Proxy subscription: servers listed, fastest picked, manual choice, refresh', ok: true });
    need(!el('proxy-direct'), 'Always-direct card shown in PAC mode');
    await api('proxy_set_mode', 'split'); await api('hub_refresh', ['proxy']);
    await go('proxy', 'proxy-direct-queue-b');
    await click('proxy-direct-queue-b');
    await wait(async () => (await api('proxy_state')).direct_lists.includes('queue-b'), 'Always-direct list not saved');
    need(el('proxy-direct-queue-b').getAttribute('aria-checked') === 'true', 'Always-direct checkbox not checked');
    await click('proxy-direct-queue-b');
    await wait(async () => !(await api('proxy_state')).direct_lists.includes('queue-b'), 'Always-direct list not removed');
    await wait(() => el('proxy-direct-queue-b').getAttribute('aria-checked') === 'false', 'Always-direct checkbox stuck');
    await api('proxy_set_mode', 'pac'); await api('hub_refresh', ['proxy']);
    await wait(() => !el('proxy-direct'), 'Always-direct card left in PAC mode');
    steps.push({ name: 'Always-direct lists toggle in TUN modes and hide in PAC', ok: true });
    await go('lists', 'list-row-queue-b'); await click('list-row-queue-b');
    await wait(() => el('lists-textarea'), 'Recovery editor missing');
    const recovering = (await api('lists_read', 'queue-b')) + 'recover.example\n';
    input('lists-textarea', recovering); await sleep(20); Pages.go('dashboard');
    await wait(async () => (await api('__smoke_failures')) === 1, 'Failed save not exercised');
    await go('lists', 'list-row-queue-b'); await click('list-row-queue-b');
    await wait(() => el('lists-textarea')?.value === recovering, 'Failed draft lost after navigation');
    need(el('lists-status')?.dataset.state === 'error', 'Failed draft not marked for retry');
    el('lists-textarea').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    await wait(() => el('lists-status')?.dataset.state === 'saved', 'Failed draft not retried');
    need((await api('lists_read', 'queue-b')).includes('recover.example'), 'Recovered draft not persisted');
    steps.push({ name: 'A failed save after navigation retains and restores the list draft', ok: true });
    return JSON.stringify(steps);
  } catch (error) {
    steps.push({ name: String(error), ok: false });
    return JSON.stringify(steps);
  } finally {
    Bridge.call = realCall;
  }
})()
