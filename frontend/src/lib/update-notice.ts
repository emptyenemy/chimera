import { useEffect } from "react"

import { fmtVersion } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { useStore } from "@/lib/store"
import type { SelfUpdateState } from "@/lib/types"

let notified: string | null = null

/** Уведомление о новой версии — один раз за сессию на каждую версию. В настройках своё
    сообщение у кнопки «Проверить», там не дублируем. */
export function useUpdateNotice(): void {
  const upd = useStore<SelfUpdateState>("selfupdate")
  useEffect(() => {
    if (!upd?.update || !upd.latest || upd.latest === notified) return
    notified = upd.latest
    if (router.current === "settings") return
    notify.info(t("update.toast.title", { version: fmtVersion(upd.latest) }), t("update.toast.desc"))
  }, [upd])
}
