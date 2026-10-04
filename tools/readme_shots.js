(async () => {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const el = id => document.querySelector(`[data-testid="${id}"]`);
  const wait = async (fn, message) => { for (let i = 0; i < 200; i++) { if (await fn()) return; await sleep(75); } throw new Error(message); };
  try {
    Pages.go("autotune");
    await wait(() => el("autotune-start") && !el("autotune-start").disabled, "Auto-setup page not ready");
    el("autotune-start").click();
    await wait(() => el("autotune-result"), "Result did not appear");
    await sleep(400);   // анимации карточки — до снимка
    document.querySelector("main")?.scrollTo(0, 0);
    return JSON.stringify([{ name: "Auto-setup result on screen", ok: true }]);
  } catch (error) {
    return JSON.stringify([{ name: String(error), ok: false }]);
  }
})()
