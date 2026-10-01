import { useState } from "react"
import {
  CircleAlertIcon,
  FlaskConicalIcon,
  RotateCcwIcon,
  TimerIcon,
  XIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store, useStore } from "@/lib/store"
import type { AppInfo } from "@/lib/types"

import type { TrialKind as Kind, TrialState } from "@/lib/trials"

const message = (error: unknown) =>
  error instanceof Error ? error.message : String(error)
const kindLabel = (kind: Kind | null) =>
  t(
    kind
      ? ({
          strategy: "trial.kind.strategy",
          hosts: "trial.kind.hosts",
          tun: "trial.kind.tun",
        }[kind] ?? "trial.kind.unknown")
      : "trial.kind.unknown"
  )

export function TrialButton({
  kind,
  target,
  disabled,
  label,
}: {
  kind: Kind
  target: string
  disabled?: boolean
  label?: string
}) {
  const app = useStore<AppInfo>("app")
  const trial = useStore<TrialState>("trial")
  const [open, setOpen] = useState(false)
  const [domains, setDomains] = useState("example.com, cloudflare.com")
  const [seconds, setSeconds] = useState("60")
  const [mode, setMode] = useState(target === "split" ? "split" : "tun")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const duration = Number(seconds)
  const validDuration =
    Number.isInteger(duration) && duration >= 15 && duration <= 300

  async function start() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await api<TrialState>(
        "trial_start",
        kind,
        kind === "tun" ? mode : target,
        duration,
        domains.split(/[\s,]+/).filter(Boolean)
      )
      store.set("trial", result)
      setOpen(false)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        data-testid={`trial-open-${kind}`}
        disabled={disabled || app?.admin === false || !!trial?.active}
        onClick={() => {
          setError(null)
          setOpen(true)
        }}
      >
        <FlaskConicalIcon data-icon="inline-start" />
        {label ?? t("trial.try")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value)
        }}
      >
        <DialogContent data-testid="trial-dialog" showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>
              {t("trial.title", { kind: kindLabel(kind) })}
            </DialogTitle>
            <DialogDescription>{t("trial.description")}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            {kind === "tun" ? (
              <Field>
                <FieldLabel>{t("trial.mode")}</FieldLabel>
                <ToggleGroup
                  variant="outline"
                  value={[mode]}
                  disabled={busy}
                  onValueChange={(values) => {
                    if (values[0]) setMode(values[0])
                  }}
                  aria-label={t("trial.mode")}
                >
                  <ToggleGroupItem value="tun">
                    {t("proxy.mode.tun")}
                  </ToggleGroupItem>
                  <ToggleGroupItem value="split">
                    {t("proxy.mode.split")}
                  </ToggleGroupItem>
                </ToggleGroup>
              </Field>
            ) : (
              <Field>
                <FieldLabel>{t("trial.target")}</FieldLabel>
                <FieldDescription>
                  {kind === "hosts"
                    ? t(
                        target === "on"
                          ? "hosts.status.enable"
                          : "hosts.status.disable"
                      )
                    : target}
                </FieldDescription>
              </Field>
            )}
            <Field data-invalid={!validDuration}>
              <FieldLabel htmlFor={`trial-seconds-${kind}`}>
                {t("trial.seconds")}
              </FieldLabel>
              <Input
                id={`trial-seconds-${kind}`}
                data-testid="trial-seconds"
                type="number"
                min={15}
                max={300}
                step={1}
                aria-invalid={!validDuration}
                value={seconds}
                disabled={busy}
                onChange={(e) => setSeconds(e.target.value)}
              />
              <FieldDescription>{t("trial.secondsHint")}</FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor={`trial-domains-${kind}`}>
                {t("trial.domains")}
              </FieldLabel>
              <Input
                id={`trial-domains-${kind}`}
                data-testid="trial-domains"
                value={domains}
                disabled={busy}
                onChange={(e) => setDomains(e.target.value)}
              />
              <FieldDescription>{t("trial.domainsHint")}</FieldDescription>
            </Field>
          </FieldGroup>
          {error && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              data-testid="trial-start"
              disabled={
                busy || !validDuration || !domains.trim() || !!trial?.active
              }
              onClick={() => void start()}
            >
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <FlaskConicalIcon data-icon="inline-start" />
              )}
              {t("trial.start")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function TrialBanner() {
  const state = useStore<TrialState>("trial")
  const [busy, setBusy] = useState(false)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const active = state?.active
  const trial = active ?? state?.last
  if (!trial || (!active && trial.id === dismissed)) return null
  const failed = trial.phase === "rollback_failed" || trial.phase === "invalid"
  const title = active
    ? t("trial.pending", {
        kind: kindLabel(trial.kind),
        seconds: trial.seconds_left,
      })
    : t(trial.phase === "confirmed" ? "trial.kept" : "trial.reverted")

  async function finish(keep: boolean) {
    if (busy || !active?.id) return
    setBusy(true)
    try {
      const result = keep
        ? await api<TrialState>("trial_confirm", active.id)
        : await api<TrialState>("trial_revert", active.id)
      store.set("trial", result)
    } catch (e) {
      notify.error(t("common.failed"), message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="mx-auto w-full max-w-[1080px] px-8 pt-7"
      data-testid="trial-banner"
    >
      <Alert variant={failed ? "destructive" : "default"}>
        {failed ? <CircleAlertIcon /> : <TimerIcon />}
        <AlertTitle>{failed ? t("trial.rollbackFailed") : title}</AlertTitle>
        <AlertDescription className="flex flex-col gap-3">
          <p>
            {trial.error
              ? t(trial.error)
              : active
                ? t(trial.checks_done ? "trial.ready" : "trial.checking")
                : t(
                    trial.reason === "check_failed"
                      ? "trial.checkFailed"
                      : trial.phase === "confirmed"
                        ? "trial.keptHint"
                        : "trial.revertedHint"
                  )}
          </p>
          {!!trial.checks?.length && (
            <div className="flex flex-wrap gap-2">
              {trial.checks.map((check) => (
                <Badge key={check.domain} variant="outline">
                  <span
                    className={
                      check.status === "ok" || check.status === "challenge"
                        ? "text-success"
                        : "text-destructive"
                    }
                  >
                    {check.status === "ok" || check.status === "challenge"
                      ? "✓"
                      : "×"}
                  </span>
                  {check.domain}
                </Badge>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {active ? (
              <>
                <Button
                  size="sm"
                  data-testid="trial-keep"
                  disabled={
                    busy ||
                    failed ||
                    !active.id ||
                    !trial.checks_done ||
                    trial.phase !== "pending" ||
                    trial.seconds_left <= 0
                  }
                  onClick={() => void finish(true)}
                >
                  {busy && <Spinner data-icon="inline-start" />}
                  {t("trial.keep")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="trial-revert"
                  disabled={busy || !active.id}
                  onClick={() => void finish(false)}
                >
                  <RotateCcwIcon data-icon="inline-start" />
                  {t("trial.revert")}
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                data-testid="trial-dismiss"
                onClick={() => setDismissed(trial.id)}
              >
                <XIcon data-icon="inline-start" />
                {t("common.close")}
              </Button>
            )}
          </div>
        </AlertDescription>
      </Alert>
    </div>
  )
}
