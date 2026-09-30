import { LANGUAGE_SETTINGS, setLanguageSetting, useLanguageSetting } from "@/lib/language"

import { useState, type ReactNode } from "react"
import { SettingsIcon, SparklesIcon, Trash2Icon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { useStore } from "@/lib/store"
import {
  AUTOSTART_KEY,
  fmtBytes,
  setConfig,
  toggleAutostart,
  useConfig,
  usePending,
  type AppInfoFull,
  type AutostartState,
} from "@/pages/settings/state"

/** Строка настройки: слева название и пояснение, справа элемент управления. */
export function SettingRow({ id, title, hint, children }: { id?: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <Field orientation="horizontal">
      <FieldContent>
        <FieldLabel htmlFor={id}>{title}</FieldLabel>
        {hint && <FieldDescription>{hint}</FieldDescription>}
      </FieldContent>
      {children}
    </Field>
  )
}

export function CardTitleIcon({ icon: Icon, children }: { icon: typeof SettingsIcon; children: ReactNode }) {
  return (
    <CardTitle className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" />
      {children}
    </CardTitle>
  )
}

export { AppearanceCard as ThemeCard } from "@/pages/settings/appearance"

export function LanguageCard() {
  const state = useLanguageSetting()
  return (
    <Card data-testid="settings-language">
      <CardHeader><CardTitle>{t("settings.lang.title")}</CardTitle></CardHeader>
      <CardContent>
        <FieldGroup>
          <SettingRow title={t("settings.lang.title")} hint={t("settings.lang.hint")}>
            <ToggleGroup value={[state.setting]} disabled={state.pending} onValueChange={(v) => {
              if (v[0]) void setLanguageSetting(v[0] as typeof state.setting)
            }} variant="outline" size="sm" aria-label={t("settings.lang.title")}>
              {LANGUAGE_SETTINGS.map((mode) => (
                <ToggleGroupItem key={mode} value={mode} data-testid={`settings-lang-${mode}`}>
                  {t(`settings.lang.${mode}`)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </SettingRow>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

const ENGINES = [
  { id: "pyside6", titleKey: "settings.engine.pyside6", dev: false },
  { id: "pywebview", titleKey: "settings.engine.pywebview", dev: true },
  { id: "browser", titleKey: "settings.engine.browser", dev: false },
]

export function GeneralCard() {
  const config = useConfig()
  const autostart = useStore<AutostartState>(AUTOSTART_KEY)
  const app = useStore<AppInfoFull>("app")
  const pending = usePending()
  return (
    <Card data-testid="settings-general">
      <CardHeader>
        <CardTitleIcon icon={SettingsIcon}>{t("settings.general.title")}</CardTitleIcon>
      </CardHeader>
      <CardContent>
        {!config ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <FieldGroup>
            <SettingRow id="set-autostart" title={t("settings.autostart.title")} hint={t("settings.autostart.hint")}>
              {autostart ? (
                <div className="flex items-center gap-2">
                  {pending.autostart && <Spinner className="text-muted-foreground" />}
                  <Switch
                    id="set-autostart"
                    data-testid="settings-autostart"
                    checked={autostart.enabled}
                    disabled={!autostart.supported || !!pending.autostart}
                    onCheckedChange={(v) => void toggleAutostart(v)}
                  />
                </div>
              ) : (
                <Skeleton className="h-5 w-8" />
              )}
            </SettingRow>
            <SettingRow id="set-tray" title={t("settings.tray.title")} hint={t("settings.tray.hint")}>
              <Switch
                id="set-tray"
                data-testid="settings-close-to-tray"
                checked={config.close_to_tray !== false}
                disabled={!!pending.close_to_tray}
                onCheckedChange={(v) => void setConfig("close_to_tray", v)}
              />
            </SettingRow>
            <SettingRow id="set-elevate" title={t("settings.elevate.title")} hint={t("settings.elevate.hint")}>
              <Switch
                id="set-elevate"
                data-testid="settings-auto-elevate"
                checked={config.auto_elevate !== false}
                disabled={!!pending.auto_elevate}
                onCheckedChange={(v) => void setConfig("auto_elevate", v)}
              />
            </SettingRow>
            <SettingRow title={t("settings.engine.title")} hint={t("settings.engine.hint")}>
              <ToggleGroup
                variant="outline"
                value={[config.ui_backend ?? "pyside6"]}
                disabled={!!pending.ui_backend}
                onValueChange={(v) => v[0] && void setConfig("ui_backend", v[0])}
                data-testid="settings-engine"
              >
                {ENGINES.filter((en) => !app?.ui_backends || app.ui_backends.includes(en.id)).map((en) => (
                  <ToggleGroupItem key={en.id} value={en.id} data-testid={`settings-engine-${en.id}`}>
                    {t(en.titleKey)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </SettingRow>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

interface DiscordReply {
  cleared?: { name: string }[]
  freed_bytes?: number
  note?: string
}

// Обслуживание: то, что у Flowseal живёт в меню service.bat
export function MaintenanceCard() {
  const [busy, setBusy] = useState(false)
  const clear = async () => {
    const ok = await confirmDialog({
      title: t("settings.discord.confirmTitle"),
      description: t("settings.discord.confirmDesc"),
      confirmText: t("settings.discord.confirm"),
    })
    if (!ok) return
    setBusy(true)
    try {
      const r = await api<DiscordReply>("discord_clear_cache")
      if (!r) return
      if (!r.cleared?.length) notify.info(t("settings.discord.nothing"), r.note || t("settings.discord.notFound"))
      else notify.success(t("settings.discord.done", { size: fmtBytes(r.freed_bytes) }), r.cleared.map((c) => c.name).join(", "))
    } catch (e) {
      notify.error(t("settings.discord.failed"), e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card data-testid="settings-maintenance">
      <CardHeader>
        <CardTitleIcon icon={SparklesIcon}>{t("settings.maintenance.title")}</CardTitleIcon>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <SettingRow title={t("settings.discord.title")} hint={t("settings.discord.hint")}>
            <Button variant="outline" size="sm" data-testid="settings-discord-cache" disabled={busy} onClick={() => void clear()}>
              {busy ? <Spinner data-icon="inline-start" /> : <Trash2Icon data-icon="inline-start" />}
              {t("settings.discord.button")}
            </Button>
          </SettingRow>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
