/* Обновления: сама программа (хаб: selfupdate, ui/updater.py) и внешние компоненты
   (git-источники: стратегии Flowseal, zapret2, tg-ws-proxy, ui/upstream). */

import { useState } from "react"
import {
  ArrowUpRightIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  DownloadIcon,
  ExternalLinkIcon,
  GitBranchIcon,
  PackageIcon,
  RefreshCwIcon,
  ServerIcon,
  TerminalIcon,
  type LucideIcon,
} from "lucide-react"

import { BrandLogo } from "@/components/app/brand-logo"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { FieldGroup } from "@/components/ui/field"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { fmtVersion } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { useStore } from "@/lib/store"
import { CardTitleIcon, SettingRow } from "@/pages/settings/general"
import { BUSY_KEY, GROUP_KEY, SOURCES_KEY, checkAll, checkOne, updateAllConfirm, updateOneConfirm, type Busy, type Source, type SourceGroup } from "@/pages/settings/sources"
import { setConfig, useConfig, usePending, type AppInfoFull } from "@/pages/settings/state"

// --- обновление самой программы ------------------------------------------------

interface SelfUpdate {
  current?: string
  latest?: string | null
  update?: boolean
  installable?: boolean
  url?: string | null
  error?: string | null
  checked_at?: number | null
  checking?: boolean
  stage?: string
  progress?: number
  frozen?: boolean
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

async function installApp(s: SelfUpdate) {
  if (!s.installable) return
  const ok = await confirmDialog({
    title: t("settings.app.installTitle", { version: fmtVersion(s.latest) }),
    description: t("settings.app.installDesc"),
    confirmText: t("settings.app.install.confirm"),
  })
  if (!ok) return
  try {
    await api("selfupdate_install")
  } catch (e) {
    notify.error(t("settings.app.installFailed"), errMsg(e))
  }
}

type Tone = "default" | "secondary" | "destructive" | "outline"

interface AppStatus {
  text: string
  badge?: { label: string; variant: Tone; icon: LucideIcon; spin?: boolean }
}

function appStatus(s: SelfUpdate, checking: boolean): AppStatus {
  if (checking || s.checking) return { text: t("settings.app.checking"), badge: { label: t("settings.badge.checking"), variant: "secondary", icon: RefreshCwIcon, spin: true } }
  if (s.stage === "downloading")
    return { text: t("settings.app.downloading", { version: fmtVersion(s.latest), pct: Math.round((s.progress || 0) * 100) }) }
  if (s.stage === "installing")
    return { text: t("settings.app.installing"), badge: { label: t("settings.badge.installing"), variant: "secondary", icon: RefreshCwIcon, spin: true } }
  if (s.error) return { text: s.error, badge: { label: t("settings.badge.error"), variant: "destructive", icon: CircleAlertIcon } }
  if (s.update) return { text: t("settings.app.available", { version: fmtVersion(s.latest) }), badge: { label: t("settings.badge.update"), variant: "default", icon: ArrowUpRightIcon } }
  if (s.checked_at) {
    const time = new Date(s.checked_at * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    return { text: t("settings.app.latest", { time }), badge: { label: t("settings.badge.latest"), variant: "outline", icon: CircleCheckIcon } }
  }
  return { text: t("settings.app.never") }
}

function StatusBadge({ badge }: { badge: NonNullable<AppStatus["badge"]> }) {
  const Icon = badge.icon
  return (
    <Badge variant={badge.variant}>
      {badge.spin ? <Spinner data-icon="inline-start" /> : <Icon data-icon="inline-start" />}
      {badge.label}
    </Badge>
  )
}

export function AppUpdateCard({ onNotes }: { onNotes: () => void }) {
  const s = useStore<SelfUpdate>("selfupdate")
  const config = useConfig()
  const pending = usePending()
  const [checking, setChecking] = useState(false)
  if (!s || !config) {
    return (
      <Card>
        <CardHeader>
          <CardTitleIcon icon={DownloadIcon}>{t("settings.app.title")}</CardTitleIcon>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }

  const check = async () => {
    setChecking(true)
    try {
      const res = await api<SelfUpdate>("selfupdate_check")
      if (res?.error) notify.error(t("settings.app.checkFailed"), res.error)
      else if (res?.update) notify.info(t("settings.app.foundToast", { version: fmtVersion(res.latest) }))
      else notify.success(t("settings.app.latestToast"))
    } catch (e) {
      notify.error(t("settings.app.checkFailed"), errMsg(e))
    } finally {
      setChecking(false)
    }
  }

  const st = appStatus(s, checking)
  const busy = checking || !!s.checking || s.stage === "downloading" || s.stage === "installing"
  const canOffer = !!s.update && s.stage !== "downloading" && s.stage !== "installing"
  const why = !s.frozen ? t("settings.app.installGit") : t("settings.app.installNoSum")
  const channel = config.update_channel || "stable"
  return (
    <Card data-testid="settings-app-update">
      <CardHeader>
        <CardTitleIcon icon={DownloadIcon}>{t("settings.app.title")}</CardTitleIcon>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <div className="flex items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted p-2 text-foreground">
              <BrandLogo />
            </div>
            <div className="flex min-w-0 grow flex-col gap-0.5">
              <div className="font-medium" data-testid="settings-app-version">
                {t("settings.app.name", { version: fmtVersion(s.current) })}
              </div>
              <div className="truncate text-muted-foreground" title={s.error ?? undefined} data-testid="settings-app-status">
                {st.text}
                {(
                  <>
                    {" · "}
                    <button
                      type="button"
                      className="text-foreground underline underline-offset-4"
                      data-testid="settings-app-notes"
                      onClick={onNotes}
                    >
                      {t("settings.app.notes")}
                    </button>
                  </>
                )}
              </div>
            </div>
            {st.badge && <StatusBadge badge={st.badge} />}
            <Button variant="outline" size="sm" data-testid="settings-app-check" disabled={busy} onClick={() => void check()}>
              <RefreshCwIcon data-icon="inline-start" />
              {t("settings.check")}
            </Button>
            {canOffer &&
              (s.installable ? (
                <Button size="sm" data-testid="settings-app-install" onClick={() => void installApp(s)}>
                  <DownloadIcon data-icon="inline-start" />
                  {t("settings.app.installTo", { version: fmtVersion(s.latest) })}
                </Button>
              ) : (
                <Tooltip>
                  <TooltipTrigger render={<span tabIndex={0} />}>
                    <Button variant="outline" size="sm" disabled data-testid="settings-app-install">
                      <DownloadIcon data-icon="inline-start" />
                      {t("settings.app.installTo", { version: fmtVersion(s.latest) })}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{why}</TooltipContent>
                </Tooltip>
              ))}
          </div>
          {s.stage === "downloading" && <Progress value={Math.round((s.progress || 0) * 100)} data-testid="settings-app-progress" />}
          <SettingRow title={t("settings.channel.title")} hint={t("settings.channel.hint")}>
            <ToggleGroup
              variant="outline"
              value={[channel]}
              disabled={!!pending.update_channel}
              onValueChange={(v) => v[0] && void setConfig("update_channel", v[0])}
              data-testid="settings-channel"
            >
              <ToggleGroupItem value="stable" data-testid="settings-channel-stable">
                {t("settings.channel.stable")}
              </ToggleGroupItem>
              <ToggleGroupItem value="beta" data-testid="settings-channel-beta">
                {t("settings.channel.beta")}
              </ToggleGroupItem>
            </ToggleGroup>
          </SettingRow>
          <SettingRow id="set-update-check" title={t("settings.updateCheck.title")} hint={t("settings.updateCheck.hint")}>
            <Switch
              id="set-update-check"
              data-testid="settings-update-check"
              checked={config.update_check !== false}
              disabled={!!pending.update_check}
              onCheckedChange={(v) => void setConfig("update_check", v)}
            />
          </SettingRow>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

// --- внешние компоненты --------------------------------------------------------

const SOURCE_ICONS: Record<string, LucideIcon> = {
  tag: GitBranchIcon,
  commit: GitBranchIcon,
  pin: PackageIcon,
  service: ServerIcon,
  python: TerminalIcon,
}

function SourceBadge({ s, busy }: { s: Source; busy?: "check" | "update" }) {
  if (busy)
    return (
      <Badge variant="secondary">
        <Spinner data-icon="inline-start" />
        {t(busy === "update" ? "settings.badge.updating" : "settings.badge.checking")}
      </Badge>
    )
  if (s.error)
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="destructive" />}>
          <CircleAlertIcon data-icon="inline-start" />
          {t("settings.badge.error")}
        </TooltipTrigger>
        <TooltipContent>{s.error}</TooltipContent>
      </Tooltip>
    )
  if (s.latest === undefined) return null // не проверяли — рядом и так кнопка «Проверить»
  if (s.update)
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge />}>
          <ArrowUpRightIcon data-icon="inline-start" />
          {t("settings.badge.update")}
        </TooltipTrigger>
        <TooltipContent>{t("settings.src.available", { version: String(s.latest) })}</TooltipContent>
      </Tooltip>
    )
  return (
    <Badge variant="outline">
      <CircleCheckIcon data-icon="inline-start" />
      {t("settings.badge.latest")}
    </Badge>
  )
}

function SourceRow({ s }: { s: Source }) {
  const busy = useStore<Busy>(BUSY_KEY)?.[s.name]
  const Icon = SOURCE_ICONS[s.kind] ?? PackageIcon
  return (
    <TableRow data-testid={`settings-src-${s.name}`}>
      <TableCell>
        <div className="flex items-center gap-2">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <button
            type="button"
            className="flex items-center gap-1.5 font-medium underline-offset-4 hover:underline"
            onClick={() => s.repo && void api("open_url", s.repo).catch(() => {})}
          >
            {s.name}
            <ExternalLinkIcon className="size-3 text-muted-foreground" />
          </button>
        </div>
      </TableCell>
      <TableCell className="font-mono text-muted-foreground">{s.version || s.current || "—"}</TableCell>
      <TableCell>
        <SourceBadge s={s} busy={busy} />
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="xs" data-testid={`settings-src-check-${s.name}`} disabled={!!busy} onClick={() => void checkOne(s.name)}>
            <RefreshCwIcon data-icon="inline-start" />
            {t("settings.check")}
          </Button>
          {s.update && !busy && (
            <Button
              size="xs"
              variant={s.updatable ? "default" : "outline"}
              data-testid={`settings-src-update-${s.name}`}
              disabled={!s.updatable}
              title={s.updatable ? undefined : t("settings.src.pinned")}
              onClick={() => void updateOneConfirm(s.name)}
            >
              <DownloadIcon data-icon="inline-start" />
              {t("settings.src.update")}
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

// Компоненты обновляются через git — это есть только при запуске из исходников;
// в собранной программе карточки нет. Пиннутые версии, Python, шрифты и онлайн-сервис
// пользователь сам не обновляет.
export function SourcesCard() {
  const sources = useStore<Source[]>(SOURCES_KEY)
  const appFrozen = useStore<AppInfoFull>("app")?.frozen
  const updFrozen = useStore<SelfUpdate>("selfupdate")?.frozen
  const frozen = appFrozen || updFrozen
  const group = useStore<SourceGroup>(GROUP_KEY)
  const allBusy = group?.updating ? "update" : group?.checking ? "check" : null
  if (frozen) return null
  const rows = (sources ?? []).filter((s) => s.kind === "tag" || s.kind === "commit")
  return (
    <Card data-testid="settings-sources">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <CardTitleIcon icon={PackageIcon}>{t("settings.src.title")}</CardTitleIcon>
        <CardAction className="flex max-w-full flex-wrap gap-2">
          <Button variant="outline" size="sm" data-testid="settings-src-check-all" disabled={!!allBusy} onClick={() => void checkAll()}>
            {allBusy === "check" ? <Spinner data-icon="inline-start" /> : <RefreshCwIcon data-icon="inline-start" />}
            {t("settings.src.checkAll")}
          </Button>
          <Button size="sm" data-testid="settings-src-update-all" disabled={!!allBusy} onClick={() => void updateAllConfirm()}>
            {allBusy === "update" ? <Spinner data-icon="inline-start" /> : <DownloadIcon data-icon="inline-start" />}
            {t("settings.src.updateAll")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!sources ? (
          <Skeleton className="h-40 w-full" />
        ) : rows.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.src.col.name")}</TableHead>
                <TableHead>{t("settings.src.col.version")}</TableHead>
                <TableHead>{t("settings.src.col.status")}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((s) => (
                <SourceRow key={s.name} s={s} />
              ))}
            </TableBody>
          </Table>
        ) : (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <PackageIcon />
              </EmptyMedia>
              <EmptyTitle>{t("settings.src.empty")}</EmptyTitle>
              <EmptyDescription>{t("settings.src.emptyHint")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </CardContent>
    </Card>
  )
}
