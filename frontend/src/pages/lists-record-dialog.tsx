/* «Записать домены сайта»: открываешь сайт, пока идёт запись, — Chimera показывает, какие
   домены ему понадобились (разница кэша DNS Windows), и добавляет выбранные в список. */

import { useEffect, useState } from "react"
import { PlayIcon, SquareIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { applyErrors, patchList, type ListInfo, type SaveInfo } from "@/pages/lists-data"

interface RecDomain {
  domain: string
  hosts: string[]
  tracker?: boolean
}

interface RecResult {
  domains?: RecDomain[]
  flushed?: boolean
  seconds?: number
}

type Phase = "intro" | "recording" | "result"

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function RecordDialog({
  lists,
  onClose,
  onAdded,
}: {
  lists: ListInfo[]
  onClose: () => void
  onAdded: (name: string) => void
}) {
  const [phase, setPhase] = useState<Phase>("intro")
  const [busy, setBusy] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [result, setResult] = useState<RecResult | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [target, setTarget] = useState(lists[0]?.name ?? "")

  useEffect(() => {
    if (phase !== "recording") return
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(id)
  }, [phase])

  const start = async () => {
    setBusy(true)
    try {
      await api("dns_record_start")
      setSeconds(0)
      setPhase("recording")
    } catch (e) {
      notify.error(t("lists.record.startFailed"), msg(e))
    } finally {
      setBusy(false)
    }
  }

  const stop = async () => {
    setBusy(true)
    try {
      const res = await api<RecResult | null>("dns_record_stop")
      setResult(res ?? {})
      setChosen(new Set((res?.domains ?? []).filter((d) => !d.tracker).map((d) => d.domain)))
      setPhase("result")
    } catch (e) {
      notify.error(t("lists.record.stopFailed"), msg(e))
      setPhase("intro")
    } finally {
      setBusy(false)
    }
  }

  const add = async () => {
    if (!chosen.size) return notify.warning(t("lists.record.pickOne"))
    if (!target) return notify.warning(t("lists.record.noList"), t("lists.record.noListDesc"))
    setBusy(true)
    try {
      const text = (await api<string>("lists_read", target)) ?? ""
      const have = new Set(text.split(/\r?\n/).map((s) => s.trim()))
      const fresh = (result?.domains ?? []).map((d) => d.domain).filter((d) => chosen.has(d) && !have.has(d))
      if (!fresh.length) {
        notify.info(t("lists.record.allExist"))
        return onClose()
      }
      const info = await api<SaveInfo | null>("lists_save", target, text.replace(/\s*$/, "") + "\n" + fresh.join("\n") + "\n")
      if (info) patchList(target, { count: info.count })
      applyErrors(info, "lists.saveApplyFailed")
      notify.success(t("lists.record.added", { name: target, n: fresh.length }))
      onAdded(target)
      onClose()
    } catch (e) {
      notify.error(t("lists.record.addFailed"), msg(e))
    } finally {
      setBusy(false)
    }
  }

  const domains = result?.domains ?? []
  const items = lists.map((f) => ({ label: f.name, value: f.name }))

  let body
  let footer
  if (phase === "intro") {
    body = (
      <div className="flex flex-col gap-3" data-testid="rec-intro">
        <p>{t("lists.record.intro")}</p>
        <p className="text-muted-foreground">{t("lists.record.introNote")}</p>
      </div>
    )
    footer = (
      <StartFooter busy={busy} label={t("lists.record.start")} onStart={() => void start()} onClose={onClose} />
    )
  } else if (phase === "recording") {
    body = (
      <div className="flex flex-col gap-3" data-testid="rec-running">
        <p className="font-medium">{t("lists.record.running")}</p>
        <p className="text-muted-foreground">
          {t("lists.record.elapsed", { n: seconds })}
        </p>
      </div>
    )
    footer = (
      <Button data-testid="rec-stop" disabled={busy} onClick={() => void stop()}>
        {busy ? <Spinner data-icon="inline-start" /> : <SquareIcon data-icon="inline-start" />}
        {t("lists.record.stop")}
      </Button>
    )
  } else if (!domains.length) {
    body = (
      <div className="flex flex-col gap-3" data-testid="rec-empty">
        <p>{t("lists.record.none")}</p>
        <p className="text-muted-foreground">
          {t("lists.record.noneNote")}
          {result?.flushed ? "" : ` ${t("lists.record.noFlush")}`}
        </p>
      </div>
    )
    footer = (
      <StartFooter busy={busy} label={t("lists.record.retry")} onStart={() => void start()} onClose={onClose} />
    )
  } else {
    body = (
      <FieldGroup data-testid="rec-result">
        <p className="text-muted-foreground">{t("lists.record.result", { n: result?.seconds ?? 0 })}</p>
        <FieldGroup className="max-h-72 gap-3 overflow-y-auto" data-slot="checkbox-group">
          {domains.map((d, i) => (
            <Field key={d.domain} orientation="horizontal">
              <Checkbox
                id={`rec-domain-${i}`}
                data-testid={`rec-domain-${d.domain}`}
                checked={chosen.has(d.domain)}
                onCheckedChange={(on) =>
                  setChosen((prev) => {
                    const next = new Set(prev)
                    if (on) next.add(d.domain)
                    else next.delete(d.domain)
                    return next
                  })
                }
              />
              <FieldContent>
                <FieldLabel htmlFor={`rec-domain-${i}`} className="font-medium">
                  {d.domain}
                  {d.tracker && <Badge variant="outline">{t("lists.record.tracker")}</Badge>}
                </FieldLabel>
                <FieldDescription>
                  {d.hosts.slice(0, 3).join(", ")}
                  {d.hosts.length > 3 && ` ${t("lists.record.more", { n: d.hosts.length - 3 })}`}
                </FieldDescription>
              </FieldContent>
            </Field>
          ))}
        </FieldGroup>
        <Field>
          <FieldLabel htmlFor="rec-target">{t("lists.record.target")}</FieldLabel>
          <Select items={items} value={target} onValueChange={(v) => setTarget(v ?? "")}>
            <SelectTrigger id="rec-target" data-testid="rec-target" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {items.map((it) => (
                  <SelectItem key={it.value} value={it.value}>
                    {it.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      </FieldGroup>
    )
    footer = (
      <>
        <Button variant="outline" onClick={onClose}>
          {t("common.close")}
        </Button>
        <Button data-testid="rec-add" disabled={busy} onClick={() => void add()}>
          {busy && <Spinner data-icon="inline-start" />}
          {t("lists.record.add")}
        </Button>
      </>
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="rec-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("lists.record.title")}</DialogTitle>
          <DialogDescription>{t("lists.record.desc")}</DialogDescription>
        </DialogHeader>
        {body}
        <DialogFooter>{footer}</DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function StartFooter({
  busy,
  label,
  onStart,
  onClose,
}: {
  busy: boolean
  label: string
  onStart: () => void
  onClose: () => void
}) {
  return (
    <>
      <Button variant="outline" onClick={onClose}>
        {t("common.close")}
      </Button>
      <Button data-testid="rec-start" disabled={busy} onClick={onStart}>
        {busy ? <Spinner data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
        {label}
      </Button>
    </>
  )
}
