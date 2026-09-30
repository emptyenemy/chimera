import { useEffect, useState } from "react"
import {
  ArchiveIcon,
  CircleAlertIcon,
  GitCompareArrowsIcon,
  HistoryIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  ScanSearchIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { currentLocale, t } from "@/lib/i18n"
import { refreshLanguage } from "@/lib/language"
import { notify } from "@/lib/notify"
import { initTheme } from "@/lib/theme"
import { CardTitleIcon } from "@/pages/settings/general"
import { refreshAutostart, refreshConfig } from "@/pages/settings/state"

interface Backup {
  id: string
  created_at: string | null
  kind: string
  sections: string[]
  valid: boolean
  error?: string | null
}

interface BackupPreview {
  id: string
  ok: boolean
  error?: string | null
  sections: { id: string; title: string; changes: string[] }[]
  errors: string[]
  warnings?: string[]
  requires_admin: boolean
  secrets_changed: boolean
}

interface BackupComparison extends Omit<
  BackupPreview,
  "id" | "requires_admin"
> {
  left_id: string | null
  right_id: string | null
  identical: boolean
}

interface RestoreReply {
  id: string
  restored: string[]
  backup: string | null
  errors: string[]
  rolled_back: boolean
  rollback_errors: string[]
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const sectionName = (id: string) =>
  id === "config" || id === "filters"
    ? t(`settings.backups.${id}`)
    : t(`settings.share.sec.${id}`)
const dateLabel = (date: string | null) => {
  if (!date) return t("settings.backups.unknownDate")
  const value = new Date(date)
  return Number.isNaN(value.valueOf())
    ? date
    : value.toLocaleString(currentLocale() === "en" ? "en-US" : "ru-RU")
}

function BackupBrowser({ onClose }: { onClose: () => void }) {
  const [backups, setBackups] = useState<Backup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<BackupPreview | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [comparison, setComparison] = useState<BackupComparison | null>(null)
  const displayed = preview ?? comparison
  const [checking, setChecking] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [result, setResult] = useState<RestoreReply | null>(null)
  const busy = checking || restoring

  useEffect(() => {
    let active = true
    void api<Backup[]>("config_backups")
      .then((items) => {
        if (active) setBackups(items)
      })
      .catch((e: unknown) => {
        if (active) setError(message(e))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function compareSelected() {
    if (selected.length !== 2) return
    setChecking(true)
    setError(null)
    setResult(null)
    try {
      setComparison(
        await api<BackupComparison>("config_backup_compare", ...selected)
      )
    } catch (e) {
      setError(message(e))
    } finally {
      setChecking(false)
    }
  }

  async function reload() {
    setSelected([])
    setLoading(true)
    setError(null)
    try {
      setBackups(await api<Backup[]>("config_backups"))
    } catch (e) {
      setError(message(e))
    } finally {
      setLoading(false)
    }
  }

  async function inspect(id: string) {
    setChecking(true)
    setError(null)
    setResult(null)
    try {
      setPreview(await api<BackupPreview>("config_backup_preview", id))
    } catch (e) {
      setError(message(e))
    } finally {
      setChecking(false)
    }
  }

  async function restore() {
    if (!preview?.ok) return
    setRestoring(true)
    setError(null)
    try {
      const reply = await api<RestoreReply>(
        "config_backup_restore",
        preview.id,
        true
      )
      await Promise.allSettled([
        refreshConfig(),
        refreshAutostart(),
        initTheme(),
        refreshLanguage(),
      ])
      if (reply.errors.length || reply.rollback_errors.length) {
        setResult(reply)
        setPreview(null)
        await reload()
      } else {
        notify.success(
          t("settings.backups.restored"),
          reply.backup
            ? t("settings.backups.savedCurrent", { id: reply.backup })
            : undefined
        )
        onClose()
      }
    } catch (e) {
      setError(message(e))
    } finally {
      setRestoring(false)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent
        className="sm:max-w-2xl"
        showCloseButton={!busy}
        data-testid="backups-dialog"
      >
        <DialogHeader>
          <DialogTitle>
            {comparison
              ? t("settings.backups.compare")
              : preview
                ? t("settings.backups.preview")
                : t("settings.backups.title")}
          </DialogTitle>
          <DialogDescription>
            {comparison
              ? t("settings.backups.compareHint")
              : preview
                ? t("settings.backups.confirmHint")
                : t("settings.backups.description")}
          </DialogDescription>
        </DialogHeader>
        <div
          className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto"
          aria-busy={busy || loading}
        >
          {checking && (
            <p role="status" className="flex items-center gap-2">
              <Spinner />
              {t("settings.backups.preview")}
            </p>
          )}
          {error && (
            <Alert variant="destructive" data-testid="backups-error">
              <CircleAlertIcon />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {result && (
            <Alert variant="destructive" data-testid="backups-result">
              <CircleAlertIcon />
              <AlertTitle>
                {result.rolled_back && !result.rollback_errors.length
                  ? t("settings.backups.rolledBack")
                  : t("settings.backups.restoreFailed")}
              </AlertTitle>
              <AlertDescription>
                <ul className="flex flex-col gap-1">
                  {[...result.errors, ...result.rollback_errors].map(
                    (line, i) => (
                      <li key={i}>{line}</li>
                    )
                  )}
                </ul>
              </AlertDescription>
            </Alert>
          )}
          {displayed ? (
            <>
              <p
                className="font-mono text-xs break-all"
                data-testid="backup-comparison-pair"
              >
                {comparison
                  ? `${comparison.left_id ?? "—"} → ${comparison.right_id ?? "—"}`
                  : preview?.id}
              </p>
              {comparison?.identical && (
                <Alert data-testid="backup-comparison-identical">
                  <AlertDescription>
                    {t("settings.backups.identical")}
                  </AlertDescription>
                </Alert>
              )}
              {!displayed.ok && (
                <Alert variant="destructive">
                  <CircleAlertIcon />
                  <AlertDescription>
                    {[displayed.error, ...displayed.errors]
                      .filter(Boolean)
                      .join("\n") || t("settings.backups.invalid")}
                  </AlertDescription>
                </Alert>
              )}
              {displayed.sections.map((section, i) => (
                <div
                  key={section.id}
                  className="flex flex-col gap-2"
                  data-testid={`backup-preview-${section.id}`}
                >
                  {i > 0 && <Separator />}
                  <h3 className="font-medium">{section.title}</h3>
                  <ul className="flex flex-col gap-1 text-muted-foreground">
                    {section.changes.length ? (
                      section.changes.map((change, n) => (
                        <li key={n}>{change}</li>
                      ))
                    ) : (
                      <li>{t("settings.share.noChanges")}</li>
                    )}
                  </ul>
                </div>
              ))}
              {displayed.secrets_changed && (
                <Alert>
                  <HistoryIcon />
                  <AlertDescription>
                    {t("settings.backups.secrets")}
                  </AlertDescription>
                </Alert>
              )}
              {preview?.requires_admin && (
                <Alert>
                  <CircleAlertIcon />
                  <AlertDescription>
                    {t("settings.backups.admin")}
                  </AlertDescription>
                </Alert>
              )}
              {(displayed.warnings ?? []).map((warning, i) => (
                <Alert key={i}>
                  <CircleAlertIcon />
                  <AlertDescription>{warning}</AlertDescription>
                </Alert>
              ))}
            </>
          ) : loading ? (
            <>
              <Skeleton className="h-28" />
              <Skeleton className="h-28" />
            </>
          ) : !backups.length ? (
            <Empty data-testid="backups-empty">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ArchiveIcon />
                </EmptyMedia>
                <EmptyTitle>{t("settings.backups.empty")}</EmptyTitle>
                <EmptyDescription>
                  {t("settings.backups.emptyHint")}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            backups.map((backup) => (
              <Card key={backup.id} size="sm" data-testid="backup-item">
                <CardHeader>
                  <CardTitle className="flex flex-wrap items-center gap-2">
                    <span>{dateLabel(backup.created_at)}</span>
                    <Badge variant={backup.valid ? "secondary" : "destructive"}>
                      {!backup.valid
                        ? t("settings.backups.invalid")
                        : backup.kind === "manual"
                          ? t("settings.backups.manual")
                          : backup.kind === "restore"
                            ? t("settings.backups.beforeRestore")
                            : t("settings.backups.beforeImport")}
                    </Badge>
                  </CardTitle>
                  <CardDescription className="break-all">
                    {backup.id}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    {backup.sections.map(sectionName).join(", ")}
                  </p>
                  {backup.error && (
                    <p className="mt-2 text-sm text-destructive">
                      {backup.error}
                    </p>
                  )}
                </CardContent>
                <CardFooter className="flex-wrap gap-3">
                  <Field orientation="horizontal" className="w-auto">
                    <Checkbox
                      id={`compare-${backup.id}`}
                      checked={selected.includes(backup.id)}
                      disabled={
                        !backup.valid ||
                        busy ||
                        (selected.length >= 2 && !selected.includes(backup.id))
                      }
                      onCheckedChange={(checked) =>
                        setSelected((ids) =>
                          checked
                            ? [...ids, backup.id].slice(0, 2)
                            : ids.filter((id) => id !== backup.id)
                        )
                      }
                      data-testid="backup-select"
                    />
                    <FieldLabel htmlFor={`compare-${backup.id}`}>
                      {selected.includes(backup.id)
                        ? t("settings.backups.selected", {
                            n: selected.indexOf(backup.id) + 1,
                          })
                        : t("settings.backups.select")}
                    </FieldLabel>
                  </Field>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!backup.valid || busy}
                    onClick={() => void inspect(backup.id)}
                    data-testid="backup-inspect"
                  >
                    <ScanSearchIcon data-icon="inline-start" />
                    {t("settings.backups.preview")}
                  </Button>
                </CardFooter>
              </Card>
            ))
          )}
        </div>
        <DialogFooter>
          {displayed ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setPreview(null)
                setComparison(null)
                setError(null)
              }}
            >
              {t("settings.backups.back")}
            </Button>
          ) : (
            <Button
              variant="outline"
              disabled={busy || loading}
              onClick={() => void reload()}
            >
              <RefreshCwIcon data-icon="inline-start" />
              {t("settings.backups.refresh")}
            </Button>
          )}
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {t("common.close")}
          </Button>
          {!displayed && (
            <Button
              disabled={selected.length !== 2 || busy || loading}
              onClick={() => void compareSelected()}
              data-testid="backup-compare"
            >
              <GitCompareArrowsIcon data-icon="inline-start" />
              {t("settings.backups.compare")}
            </Button>
          )}
          {preview && (
            <Button
              disabled={!preview.ok || busy}
              onClick={() => void restore()}
              data-testid="backup-restore"
            >
              {restoring ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <RotateCcwIcon data-icon="inline-start" />
              )}
              {t("settings.backups.restore")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function BackupsCard() {
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  async function createSnapshot() {
    setCreating(true)
    try {
      const backup = await api<Backup>("config_backup_create")
      notify.success(t("settings.backups.created"), backup.id)
      setOpen(true)
    } catch (e) {
      notify.error(t("settings.backups.createFailed"), message(e))
    } finally {
      setCreating(false)
    }
  }
  return (
    <Card data-testid="settings-backups">
      <CardHeader>
        <CardTitleIcon icon={HistoryIcon}>
          {t("settings.backups.title")}
        </CardTitleIcon>
        <CardDescription>{t("settings.backups.description")}</CardDescription>
      </CardHeader>
      <CardFooter className="flex-wrap gap-2">
        <Button
          disabled={creating}
          onClick={() => void createSnapshot()}
          data-testid="settings-backups-create"
        >
          {creating ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <ArchiveIcon data-icon="inline-start" />
          )}
          {t("settings.backups.create")}
        </Button>
        <Button
          variant="outline"
          disabled={creating}
          onClick={() => setOpen(true)}
          data-testid="settings-backups-open"
        >
          <ArchiveIcon data-icon="inline-start" />
          {t("settings.backups.open")}
        </Button>
      </CardFooter>
      {open && <BackupBrowser onClose={() => setOpen(false)} />}
    </Card>
  )
}
