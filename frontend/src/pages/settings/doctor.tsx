/* Диагностика: проверки «почему обход может не работать» и отчёт для issue. Ничего не меняет. */

import { useState } from "react"
import { ActivityIcon, CircleCheckIcon, CircleHelpIcon, CircleXIcon, ClipboardCopyIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { FieldGroup } from "@/components/ui/field"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { copyText } from "@/lib/clipboard"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store, useStore } from "@/lib/store"
import { CardTitleIcon, SettingRow } from "@/pages/settings/general"

interface Check {
  id: string
  status: "ok" | "warn" | "fail"
  title: string
  message: string
  hint?: string
}

interface DoctorResult {
  checks: Check[]
  summary: { ok: number; warn: number; fail: number }
}

const KEY = "settings.doctor"

const ICONS: Record<Check["status"], { icon: LucideIcon; tone: string }> = {
  ok: { icon: CircleCheckIcon, tone: "text-success" },
  warn: { icon: TriangleAlertIcon, tone: "text-warning" },
  fail: { icon: CircleXIcon, tone: "text-destructive" },
}

export function DoctorCard() {
  const doctor = useStore<DoctorResult>(KEY)
  const [running, setRunning] = useState(false)
  const [copying, setCopying] = useState(false)
  const s = doctor?.summary

  const run = async () => {
    setRunning(true)
    try {
      store.set(KEY, await api<DoctorResult>("doctor_run"))
    } catch (e) {
      notify.error(t("settings.doctor.failed"), e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  const copy = async () => {
    setCopying(true)
    try {
      await copyText(await api<string>("doctor_report"))
    } catch (e) {
      notify.error(t("settings.doctor.reportFailed"), e instanceof Error ? e.message : String(e))
    } finally {
      setCopying(false)
    }
  }

  return (
    <Card data-testid="settings-doctor">
      <CardHeader>
        <CardTitleIcon icon={ActivityIcon}>{t("settings.doctor.title")}</CardTitleIcon>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <SettingRow
            title={t("settings.doctor.label")}
            hint={s ? t("settings.doctor.summary", { total: s.ok + s.warn + s.fail, warn: s.warn, fail: s.fail }) : t("settings.doctor.hint")}
          >
            <div className="flex gap-2">
              <Button variant="outline" size="sm" data-testid="settings-doctor-copy" disabled={!doctor || copying} onClick={() => void copy()}>
                {copying ? <Spinner data-icon="inline-start" /> : <ClipboardCopyIcon data-icon="inline-start" />}
                {t("settings.doctor.copy")}
              </Button>
              <Button variant="outline" size="sm" data-testid="settings-doctor-run" disabled={running} onClick={() => void run()}>
                {running ? <Spinner data-icon="inline-start" /> : <ActivityIcon data-icon="inline-start" />}
                {t("settings.doctor.run")}
              </Button>
            </div>
          </SettingRow>
          {doctor && (
            <div className="flex flex-col gap-3" data-testid="settings-doctor-list">
              {doctor.checks.map((c) => {
                const { icon: Icon, tone } = ICONS[c.status] ?? { icon: CircleHelpIcon, tone: "text-muted-foreground" }
                return (
                  <div key={c.id} className="flex items-start gap-2.5" data-testid={`doctor-${c.id}`} data-status={c.status}>
                    <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} />
                    <div className="flex flex-col gap-0.5">
                      <div className="font-medium">{c.title}</div>
                      <div className="text-muted-foreground">{c.message}</div>
                      {c.status !== "ok" && c.hint && <div>{c.hint}</div>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
