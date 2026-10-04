/* Стратегии и списки по воздуху (modules/dataupdate.py): проверка выпуска данных, предпросмотр
   изменений и установка. Состояние живёт в сторе: переключение вкладок не теряет проверку. */

import { DatabaseZapIcon, DownloadIcon, RefreshCwIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store, useStore } from "@/lib/store"
import { CardTitleIcon } from "@/pages/settings/general"

interface DataPlan {
  add: string[]
  update: string[]
  keep: string[]
  same: number
}

export interface DataCheck {
  current: string | null
  latest: string | null
  update: boolean
  installable: boolean
  plan: DataPlan | null
  min_app: string | null
  error: string | null
}

interface DataInstall {
  version: string
  added: string[]
  updated: string[]
  kept: string[]
  restarted?: boolean
  restart_error?: string
}

interface DataView {
  busy: "check" | "install" | null
  info: DataCheck | null
}

const KEY = "settings.data"
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const view = () => store.get<DataView>(KEY) ?? { busy: null, info: null }

async function checkData(): Promise<void> {
  if (view().busy) return
  store.set(KEY, { ...view(), busy: "check" })
  try {
    store.set(KEY, { busy: null, info: await api<DataCheck>("data_check") })
  } catch (e) {
    store.set(KEY, { ...view(), busy: null })
    notify.error(t("settings.data.checkFailed"), errText(e))
  }
}

async function installData(): Promise<void> {
  if (view().busy) return
  store.set(KEY, { ...view(), busy: "install" })
  try {
    const res = await api<DataInstall>("data_update")
    notify.success(t("settings.data.installed", { version: res.version }),
      [t("settings.data.counts", { add: res.added.length, update: res.updated.length, keep: res.kept.length }),
       res.restarted ? t("settings.data.restarted") : res.restart_error ?? ""].filter(Boolean).join(" "))
    store.set(KEY, { ...view(), busy: null })
    await checkData()
  } catch (e) {
    store.set(KEY, { ...view(), busy: null })
    notify.error(t("settings.data.installFailed"), errText(e))
  }
}

export function DataCard() {
  const { busy, info } = useStore<DataView>(KEY) ?? { busy: null, info: null }
  const plan = info?.plan
  return (
    <Card data-testid="settings-data">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitleIcon icon={DatabaseZapIcon}>{t("settings.data.title")}</CardTitleIcon>
          <CardDescription>{t("settings.data.desc")}</CardDescription>
        </div>
        <CardAction className="flex max-w-full flex-wrap gap-2">
          <Button variant="outline" size="sm" data-testid="settings-data-check" disabled={!!busy} onClick={() => void checkData()}>
            {busy === "check" ? <Spinner data-icon="inline-start" /> : <RefreshCwIcon data-icon="inline-start" />}
            {t("settings.data.check")}
          </Button>
          {info?.installable && (
            <Button size="sm" data-testid="settings-data-install" disabled={!!busy} onClick={() => void installData()}>
              {busy === "install" ? <Spinner data-icon="inline-start" /> : <DownloadIcon data-icon="inline-start" />}
              {t("settings.data.install", { version: info.latest ?? "" })}
            </Button>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm" data-testid="settings-data-status">
        <p className="text-muted-foreground">{t("settings.data.current", { version: info?.current ?? "—" })}</p>
        {info?.error && <p className="text-muted-foreground">{t(info.error)}</p>}
        {info && !info.error && !info.update && <p>{t("settings.data.latest")}</p>}
        {info?.update && plan && (
          <p data-testid="settings-data-plan">
            {t("settings.data.available", { version: info.latest ?? "" })}{" "}
            {t("settings.data.counts", { add: plan.add.length, update: plan.update.length, keep: plan.keep.length })}
          </p>
        )}
        {info?.update && !info.installable && info.min_app && (
          <Alert>
            <AlertDescription>{t("settings.data.needApp", { version: info.min_app })}</AlertDescription>
          </Alert>
        )}
        {!!plan?.keep.length && info?.update && (
          <p className="text-[13px] text-muted-foreground" data-testid="settings-data-kept">
            {t("settings.data.kept", { files: plan.keep.join(", ") })}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
