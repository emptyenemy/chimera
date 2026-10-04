(async () => {
  const steps = [];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const need = (value, message) => { if (!value) throw new Error(message); };
  const wait = async (fn, message) => { for (let i = 0; i < 200; i++) { if (await fn()) return; await sleep(75); } throw new Error(message); };
  // Switch и Checkbox из Base UI — span: заблокированность у них в data-disabled, а не в .disabled
  const ready = id => el(id) && !el(id).matches(':disabled, [data-disabled], [aria-disabled=true]');
  const click = async id => { await wait(() => ready(id), `${id} not ready`); el(id).click(); await sleep(60); };
  const text = id => el(id)?.textContent || "";
  const call = async (method, ...args) => JSON.parse(await Bridge.call(method, JSON.stringify(args)));
  const smoke = async action => (await call("__smoke_autotune", action)).data;
  try {
    need(el("nav-autotune"), "Auto-setup is missing from the menu");
    Pages.go("autotune");
    await wait(() => el("autotune-row-youtube") && el("autotune-row-openai") && el("autotune-row-discord"), "Services not listed");
    need(text("autotune-status-youtube").includes("Не проверен"), "Unchecked service shows a status");
    steps.push({ name: "Page opens from the menu and lists the services", ok: true });

    await click("autotune-check");
    await wait(() => el("autotune-row-discord").dataset.ok === "true", "Diagnosis did not arrive");
    need(text("autotune-status-youtube").includes("Блокировка DPI"), "DPI reason missing");
    need(text("autotune-status-openai").includes("Отказ по стране"), "Region refusal missing");
    need(el("autotune-fix-youtube") && !el("autotune-fix-discord"), "Fix buttons do not follow the status");
    need((await smoke("state")).net.strategy === null, "Diagnosis changed settings");
    steps.push({ name: "Check names the reason of every unreachable service and changes nothing", ok: true });

    await click("autotune-mode-smart");
    await wait(() => text("autotune-mode-hint").includes("самый быстрый"), "Smart mode hint missing");
    await click("autotune-mode-fast");
    steps.push({ name: "Fast and smart modes switch with an explanation", ok: true });

    await smoke("hold");
    await click("autotune-start");
    await wait(() => el("autotune-running"), "Running card missing");
    await wait(() => el("nav-dot-autotune"), "Menu dot does not show the running search");
    need(text("autotune-current").length > 0 && el("autotune-progress"), "Progress is not shown");
    need((await call("proxy_stop")).ok === false, "Changes were not blocked");
    await smoke("release");
    await wait(() => el("autotune-result"), "Result did not appear");
    need(!el("nav-dot-autotune"), "Menu dot stayed after the search");
    need(el("autotune-result-youtube").dataset.ok === "true" && text("autotune-result-youtube").includes("Стратегия"), "YouTube fix missing");
    need(el("autotune-result-openai").dataset.ok === "true" && text("autotune-result-openai").includes("Hosts через"), "ChatGPT fix missing");
    need(text("autotune-result-discord").includes("Работал и раньше"), "Working service is not marked");
    need(text("autotune-summary").includes("3 из 3"), "Summary is wrong");
    need(el("autotune-row-youtube").dataset.ok === "true", "Service list did not take the result");
    const after = (await smoke("state")).net;
    need(after.strategy === "alt" && after.hosts.openai === "comss", "Result was not applied");
    steps.push({ name: "Set up everything: progress, menu dot, blocked changes, result per service", ok: true });

    await click("autotune-share");
    await wait(async () => (await smoke("state")).opened.length === 1, "Share did not open the discussion form");
    const form = (await smoke("state")).opened[0];
    need(form.startsWith("https://github.com/emptyenemy/chimera/discussions/new?") && form.includes("category=show-and-tell"),
      "Share opened something else than the discussion form");
    need(form.includes("chimera-report") && form.includes("youtube"), "Discussion form lacks the report");
    steps.push({ name: "Share opens a prefilled GitHub discussion and sends nothing itself", ok: true });

    await click("autotune-revert");
    await wait(() => el("autotune-last")?.dataset.phase === "reverted", "Revert did not finish");
    const reverted = (await smoke("state")).net;
    need(reverted.strategy === null && !reverted.hosts.openai, "Settings were not restored");
    steps.push({ name: "Undo restores the settings from before the search", ok: true });

    await click("autotune-fix-openai");
    await wait(() => el("autotune-result-openai"), "Single-service result missing");
    need(!el("autotune-result-youtube"), "Single fix touched other services");
    await click("autotune-keep");
    await wait(() => !el("autotune-result"), "Keep did not close the result");
    need((await smoke("state")).net.hosts.openai === "comss", "Kept result was rolled back");
    steps.push({ name: "Fix one service and keep the result", ok: true });

    await smoke("hold");
    await click("autotune-start");
    await wait(() => el("autotune-running"), "Second search did not start");
    await click("autotune-cancel");
    await smoke("release");
    await wait(() => el("autotune-last")?.dataset.phase === "cancelled", "Cancel did not finish");
    const cancelled = (await smoke("state")).net;
    need(cancelled.strategy === null && cancelled.hosts.openai === "comss", "Cancel did not restore the state before the search");
    steps.push({ name: "Cancel stops the search and restores the previous state", ok: true });

    await click("autotune-watch");
    await wait(async () => (await call("config_read")).data.autotune_watch === true, "Fix automatically was not saved");
    await click("autotune-watch");
    await wait(async () => (await call("config_read")).data.autotune_watch === false, "Fix automatically was not switched off");
    await smoke("watch-fix");
    await wait(() => el("autotune-result"), "Background fix result missing");
    need(text("autotune-summary").includes("сработала сама"), "Background fix is not marked");
    await click("autotune-keep");
    steps.push({ name: "Fix automatically switch persists; a background fix is marked in the result", ok: true });

    await click("autotune-method-dns"); await click("autotune-method-proxy");
    await wait(async () => JSON.stringify((await call("config_read")).data.autotune_steps) === '["strategy","hosts"]',
      "Methods were not saved");
    need(el("autotune-method-strategy").getAttribute("aria-checked") === "true", "A method that stayed on looks off");
    await click("autotune-options-toggle");
    await wait(() => el("autotune-option-strategy-alt"), "Options were not listed");
    need(!el("autotune-options-dns"), "Options of a switched-off method are still offered");
    await click("autotune-option-strategy-alt");
    await wait(async () => ((await call("config_read")).data.autotune_exclude?.strategy || []).includes("alt"),
      "Excluded option was not saved");
    await smoke("break");
    await click("autotune-check");
    await click("autotune-fix-youtube");
    await wait(() => el("autotune-result"), "Fix with narrowed methods did not finish");
    const narrowed = (await call("autotune_state")).data.active;
    need(JSON.stringify(narrowed.steps) === '["strategy","hosts"]', "The session did not use the chosen methods");
    need((await smoke("state")).net.strategy !== "alt", "An excluded strategy was tried");
    steps.push({ name: "What to try: switched-off methods and excluded options are skipped", ok: true });
  } catch (error) {
    steps.push({ name: String(error), ok: false });
  } finally {
    await smoke("release");
  }
  return JSON.stringify(steps);
})()
