(async () => {
  const steps = [];
  const need = (value, message) => { if (!value) throw new Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const wait = async (fn, message) => { for (let i = 0; i < 100; i++) { if (await fn()) return; await sleep(50); } throw new Error(message); };
  const click = async id => { await wait(() => el(id) && !el(id).disabled, `${id} not ready`); el(id).click(); await sleep(40); };
  const input = (id, value) => {
    const node = el(id);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const blur = which => el(`strat-range-${which}`).dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  const api = async (method, ...args) => {
    const result = JSON.parse(await Bridge.call(method, JSON.stringify(args)));
    if (!result.ok) throw new Error(result.error);
    return result.data;
  };
  const go = async () => {
    Pages.go('strategies');
    await wait(() => el('strat-advanced-toggle'), 'Strategies missing');
    if (!el('strat-range-tcp')) await click('strat-advanced-toggle');
    await wait(() => el('strat-range-tcp'), 'Game ranges missing');
  };
  const realCall = Bridge.call;
  let replies = 0;
  try {
    await go();
    const count = (await api('__smoke_game')).calls.length;
    input('strat-range-tcp', '80-'); await sleep(20); blur('tcp');
    await wait(() => el('strat-range-tcp').getAttribute('aria-invalid') === 'true', 'Invalid range not marked');
    need((await api('__smoke_game')).calls.length === count, 'Invalid range reached backend');
    const errorId = el('strat-range-tcp').getAttribute('aria-describedby');
    need(errorId && document.getElementById(errorId), 'Range error is not linked to input');
    steps.push({ name: 'Invalid game ranges remain local with an accessible field error', ok: true });

    Bridge.call = async (method, args) => {
      const result = await realCall(method, args);
      if (method === 'game_filter_set') { await sleep(250); replies++; }
      return result;
    };
    input('strat-range-tcp', '8000'); await sleep(20); blur('tcp'); blur('tcp');
    await wait(async () => (await api('__smoke_game')).calls.length === count + 1, 'TCP save did not start');
    input('strat-range-tcp', '9000'); await sleep(20);
    await wait(() => replies === 1, 'TCP reply not delivered'); await sleep(80);
    need(el('strat-range-tcp').value === '9000', 'Late TCP reply erased newer draft');
    blur('tcp');
    await wait(() => replies === 2, 'Latest TCP draft not saved');
    need((await api('filters_state')).game_ranges.tcp === '9000', 'Latest TCP range not persisted');
    need((await api('__smoke_game')).calls.length === count + 2, 'Repeated blur duplicated TCP save');
    steps.push({ name: 'Range saves deduplicate blur and preserve newer text during a delayed reply', ok: true });

    input('strat-range-tcp', '65000'); await sleep(20); blur('tcp');
    input('strat-range-udp', '9100'); await sleep(20); blur('udp');
    await wait(() => replies === 4, 'Queued range replies did not finish');
    need(el('strat-range-tcp').value === '65000' && el('strat-range-tcp-error'), 'Failed TCP draft was lost');
    need((await api('filters_state')).game_ranges.udp === '9100', 'TCP failure lost UDP edit');
    Pages.go('dashboard'); await sleep(80); await go();
    need(el('strat-range-tcp').value === '65000' && el('strat-range-tcp-error'), 'Failed range not restored after navigation');
    blur('tcp');
    await wait(() => replies === 5, 'Failed range not retried');
    need((await api('filters_state')).game_ranges.tcp === '65000', 'Retried TCP not persisted');
    steps.push({ name: 'A failed range preserves the other protocol and survives navigation for retry', ok: true });

    input('strat-range-tcp', '64000'); await sleep(20); blur('tcp');
    await click('strat-game-udp');
    input('strat-range-udp', '9200'); await sleep(20); blur('udp');
    await wait(() => replies === 8, 'Mode and range queue did not finish');
    const mode = await api('filters_state');
    need(mode.game === 'udp' && mode.game_ranges.udp === '9200', 'Range save restored an obsolete game mode');
    need(el('strat-game-udp').getAttribute('aria-pressed') === 'true', 'Old reply reverted mode in UI');
    steps.push({ name: 'Queued port edits preserve a concurrent mode switch', ok: true });

    const beforeReset = (await api('__smoke_game')).calls.length;
    await click('strat-range-default'); el('strat-range-default').click();
    need(el('strat-range-default').disabled, 'Reset remained available while saving');
    input('strat-range-udp', '9300'); await sleep(20);
    await wait(() => replies === 9, 'Reset reply missing'); await sleep(80);
    need(el('strat-range-udp').value === '9300', 'Reset reply erased newer UDP text');
    need((await api('__smoke_game')).calls.length === beforeReset + 1, 'Reset was submitted twice');
    blur('udp'); await wait(() => replies === 10, 'Post-reset edit not saved');
    need((await api('filters_state')).game_ranges.udp === '9300', 'Post-reset range missing');
    steps.push({ name: 'Reset runs once and preserves edits made while its reply is pending', ok: true });

    input('strat-range-udp', '9400'); await sleep(20); Pages.go('dashboard');
    await wait(() => replies === 11, 'Leaving strategies lost an unsubmitted range');
    await go();
    await wait(() => el('strat-range-udp').value === '9400', 'Confirmed range not shown after navigation');
    const beforeCancel = (await api('__smoke_game')).calls.length;
    input('strat-range-udp', '0'); await sleep(20);
    el('strat-range-udp').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(() => el('strat-range-udp').value === '9400', 'Escape did not discard the draft');
    blur('udp'); await sleep(80);
    need((await api('__smoke_game')).calls.length === beforeCancel, 'Escape caused a save');
    steps.push({ name: 'Navigation flushes unsaved ranges and Escape discards local edits', ok: true });
    return JSON.stringify(steps);
  } catch (error) {
    steps.push({ name: String(error), ok: false });
    return JSON.stringify(steps);
  } finally {
    Bridge.call = realCall;
  }
})()
