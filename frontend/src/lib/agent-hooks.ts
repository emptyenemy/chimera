/* Точки входа для агентских проверок (tools/ui_shot.mjs, tools/smoke_checks.js): те же
   window.api, window.Bridge и window.Pages, что у старого фронта. Приложению они не
   нужны — только внешним скриптам, которые выполняют код в странице. */

import { api, Bridge } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { router } from "@/lib/router"
import { PAGES } from "@/pages/registry"

declare global {
  interface Window {
    api?: typeof api
    Bridge?: typeof Bridge
    Pages?: {
      readonly list: { id: string; title: string; group: string }[]
      readonly current: string
      go(id: string): void
    }
  }
}

export function installAgentHooks(): void {
  window.api = api
  window.Bridge = Bridge
  window.Pages = {
    get list() {
      return PAGES.map((p) => ({ id: p.id, title: t(p.titleKey), group: p.groupKey ? t(p.groupKey) : "" }))
    },
    get current() {
      return router.current
    },
    go: (id) => router.go(id),
  }
}
