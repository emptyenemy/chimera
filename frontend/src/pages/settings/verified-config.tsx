import { useEffect, useRef, useState } from "react"
import { CircleCheckIcon, RotateCcwIcon, ScanSearchIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { currentLocale, t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { useTrialPending } from "@/lib/trials"

interface Check {
  domain: string
  status: string
}
interface VerifiedBackup {
  id: string
  checked_at: string
  checks: Check[]
}
interface VerifiedState {
  backup: VerifiedBackup | null
  error: string | null
}
interface VerifyReply extends VerifiedState {
  saved: boolean
  checks: Check[]
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function VerifiedConfig({
  onRestore,
}: {
  onRestore: (id: string) => void
}) {
  const [state, setState] = useState<VerifiedState | null>(null)
  const stateRevision = useRef(0)
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [checks, setChecks] = useState<Check[]>([])
  const trialPending = useTrialPending()
  const selected = [
    ...new Set(
      input
        .toLowerCase()
        .split(/[\s,;]+/)
        .filter(Boolean)
    ),
  ]
  const valid =
    selected.length >= 1 &&
    selected.length <= 6 &&
    selected.every((domain) =>
      /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(
        domain
      )
    )

  useEffect(() => {
    let active = true
    const before = stateRevision.current
    void api<VerifiedState>("config_verified")
      .then((value) => {
        if (active && before === stateRevision.current) setState(value)
      })
      .catch((e: unknown) => {
        if (active && before === stateRevision.current) setState({ backup: null, error: message(e) })
      })
    return () => {
      active = false
    }
  }, [])

  async function verify() {
    setBusy(true)
    setError(null)
    setChecks([])
    try {
      const reply = await api<VerifyReply>("config_verify", selected)
      setChecks(reply.checks)
      if (reply.saved) {
        stateRevision.current++
        setState({ backup: reply.backup, error: null })
        notify.success(t("settings.verified.saved"))
        setOpen(false)
      } else {
        setError(reply.error)
      }
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  const backup = state?.backup
  return (
    <div className="flex flex-col gap-3" data-testid="settings-verified">
      <div className="flex flex-col gap-1">
        <h3 className="font-medium">{t("settings.verified.title")}</h3>
        <p
          className="text-sm text-muted-foreground"
          data-testid="verified-summary"
        >
          {backup
            ? `${new Date(backup.checked_at).toLocaleString(currentLocale() === "en" ? "en-US" : "ru-RU")} · ${backup.checks.map((c) => c.domain).join(", ")}`
            : t(state ? "settings.verified.empty" : "common.loading")}
        </p>
      </div>
      {state?.error && (
        <Alert variant="destructive">
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={busy || trialPending}
          data-testid="verified-open"
          onClick={() => {
            setError(null)
            setChecks([])
            setOpen(true)
          }}
        >
          <ScanSearchIcon data-icon="inline-start" />
          {t("settings.verified.verify")}
        </Button>
        <Button
          variant="outline"
          disabled={!backup || busy || trialPending}
          data-testid="verified-restore"
          onClick={() => backup && onRestore(backup.id)}
        >
          <RotateCcwIcon data-icon="inline-start" />
          {t("settings.verified.restore")}
        </Button>
      </div>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value)
        }}
      >
        <DialogContent showCloseButton={!busy} data-testid="verified-dialog">
          <DialogHeader>
            <DialogTitle>{t("settings.verified.verify")}</DialogTitle>
            <DialogDescription>
              {t("settings.verified.description")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (valid && !busy && !trialPending) void verify()
            }}
          >
            <Field>
              <FieldLabel htmlFor="verified-domains">
                {t("settings.verified.domains")}
              </FieldLabel>
              <Input
                id="verified-domains"
                data-testid="verified-domains"
                value={input}
                disabled={busy}
                placeholder="youtube.com, discord.com"
                autoComplete="off"
                onChange={(event) => setInput(event.target.value)}
              />
              <FieldDescription>{t("settings.verified.hint")}</FieldDescription>
            </Field>
            {error && (
              <Alert variant="destructive" data-testid="verified-error">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {!!checks.length && (
              <div
                className="flex flex-col gap-2"
                aria-live="polite"
                data-testid="verified-checks"
              >
                {checks.map((check) => (
                  <div
                    key={check.domain}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <span className="truncate">{check.domain}</span>
                    <Badge
                      variant={check.status === "ok" ? "secondary" : "outline"}
                    >
                      {t(`settings.verified.status.${check.status}`)}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setOpen(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="submit"
                disabled={!valid || busy || trialPending}
                data-testid="verified-save"
              >
                {busy ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <CircleCheckIcon data-icon="inline-start" />
                )}
                {t(
                  busy ? "settings.verified.checking" : "settings.verified.save"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
