import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"
import { installAgentHooks } from "@/lib/agent-hooks"
import { api, initBridge } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { initLanguage } from "@/lib/language"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { loadSnapshot, store } from "@/lib/store"
import { initTheme } from "@/lib/theme"
import type { AppInfo } from "@/lib/types"
import { PAGE_IDS } from "@/pages/registry"

/* Старт как в старом core.js: мост, снимок хаба (мгновенно, всё уже опрошено), app_info,
   и только потом первая отрисовка — интерфейс не мигает пустыми карточками. */
async function boot(): Promise<void> {
  installAgentHooks()
  router.init(PAGE_IDS)

  let failure: string | null = null
  let info: AppInfo = { admin: true, version: "" }
  try {
    await initBridge()
    await initLanguage()
    await loadSnapshot().catch((e) => console.error(e))
    info = await api<AppInfo>("app_info").catch(() => info)
  } catch (e) {
    console.error(e)
    failure = e instanceof Error ? e.message : String(e)
  }
  store.set("app", info)
  await initTheme()

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
  // ждать кадр: по body.ready внешние проверки понимают, что интерфейс поднялся
  requestAnimationFrame(() => document.body.classList.add("ready"))
  if (failure) setTimeout(() => notify.error(t("boot.failed"), failure), 100)
}

void boot()
