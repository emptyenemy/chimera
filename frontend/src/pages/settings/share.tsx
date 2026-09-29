/* Обмен конфигом: поделиться частью настроек и применить чужой конфиг с предпросмотром.
   Разделы независимы; настройки обхода DPI по умолчанию выключены — у других провайдер другой. */

import { useRef, useState } from "react"
import { CircleAlertIcon, CopyIcon, DownloadIcon, FolderOpenIcon, ScanSearchIcon, SendIcon, TriangleAlertIcon, UploadIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Separator } from "@/components/ui/separator"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/bridge"
import { copyText } from "@/lib/clipboard"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { CardTitleIcon, SettingRow } from "@/pages/settings/general"

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

const SECTIONS = [
  { id: "lists", on: true, warn: false },
  { id: "proxy", on: true, warn: false },
  { id: "hosts", on: true, warn: false },
  { id: "dns", on: true, warn: false },
  { id: "telegram", on: true, warn: false },
  { id: "winws", on: false, warn: true },
]

function ExportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [chosen, setChosen] = useState<string[]>(() => SECTIONS.filter((s) => s.on).map((s) => s.id))
  const [text, setText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const build = async () => {
    if (!chosen.length) return notify.warning(t("settings.share.pickOne"))
    setBusy(true)
    try {
      setText(await api<string>("config_export", chosen))
    } catch (e) {
      notify.error(t("settings.share.buildFailed"), errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) setText(null)
      }}
    >
      <DialogContent data-testid="share-export-dialog">
        <DialogHeader>
          <DialogTitle>{t("settings.share.exportTitle")}</DialogTitle>
          <DialogDescription>{t("settings.share.exportDesc")}</DialogDescription>
        </DialogHeader>
        {text === null ? (
          <FieldGroup>
            {SECTIONS.map((s) => (
              <Field key={s.id} orientation="horizontal">
                <Checkbox
                  id={`share-${s.id}`}
                  data-testid={`share-section-${s.id}`}
                  checked={chosen.includes(s.id)}
                  onCheckedChange={(v) => setChosen((cur) => (v ? [...cur, s.id] : cur.filter((x) => x !== s.id)))}
                />
                <FieldContent>
                  <FieldLabel htmlFor={`share-${s.id}`}>
                    {t(`settings.share.sec.${s.id}`)}
                    {s.warn && <Badge variant="outline">{t("settings.share.providerDependent")}</Badge>}
                  </FieldLabel>
                  <FieldDescription>{t(`settings.share.sec.${s.id}.hint`)}</FieldDescription>
                </FieldContent>
              </Field>
            ))}
          </FieldGroup>
        ) : (
          <Field>
            <FieldDescription>{t("settings.share.copyHint")}</FieldDescription>
            <Textarea readOnly spellCheck={false} className="min-h-44 font-mono select-text" data-testid="share-export-text" value={text} onFocus={(e) => e.currentTarget.select()} />
          </Field>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          {text === null ? (
            <Button data-testid="share-build" disabled={busy} onClick={() => void build()}>
              {busy && <Spinner data-icon="inline-start" />}
              {t("settings.share.build")}
            </Button>
          ) : (
            <Button data-testid="share-copy" onClick={() => void copyText(text)}>
              <CopyIcon data-icon="inline-start" />
              {t("settings.share.copy")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface PreviewSection {
  id: string
  title: string
  provider_dependent?: boolean
  changes: string[]
  confirm: string[]
  skipped: string[]
}

interface Preview {
  ok: boolean
  error?: string
  sections: PreviewSection[]
  unknown_sections: string[]
  unknown_fields?: Record<string, string[]>
  invalid: unknown[]
  needs_confirm?: boolean
}

interface ApplyReply {
  errors?: string[]
  skipped?: Record<string, unknown[]>
  backup?: unknown
}

function PreviewView({ pv, picked, onPick, trusted, onTrust }: { pv: Preview; picked: string[]; onPick: (id: string, on: boolean) => void; trusted: boolean; onTrust: (v: boolean) => void }) {
  if (!pv.ok) {
    return (
      <Alert variant="destructive" data-testid="share-preview-error">
        <CircleAlertIcon />
        <AlertDescription>{pv.error || t("settings.share.badConfig")}</AlertDescription>
      </Alert>
    )
  }
  const notes: string[] = []
  if (pv.unknown_sections.length) notes.push(t("settings.share.unknownSections", { list: pv.unknown_sections.join(", ") }))
  const uf = Object.entries(pv.unknown_fields ?? {}).map(([k, v]) => `${k}: ${v.join(", ")}`)
  if (uf.length) notes.push(t("settings.share.unknownFields", { list: uf.join("; ") }))
  if (pv.invalid.length) notes.push(t("settings.share.invalid", { count: pv.invalid.length }))
  return (
    <div className="flex flex-col gap-3" data-testid="share-preview">
      {pv.sections.map((s, i) => (
        <div key={s.id} className="flex flex-col gap-2" data-testid={`share-preview-${s.id}`}>
          {i > 0 && <Separator />}
          <Field orientation="horizontal">
            <Checkbox id={`imp-${s.id}`} checked={picked.includes(s.id)} onCheckedChange={(v) => onPick(s.id, !!v)} data-testid={`share-pick-${s.id}`} />
            <FieldLabel htmlFor={`imp-${s.id}`}>
              {s.title}
              {s.provider_dependent && <Badge variant="outline">{t("settings.share.providerDependent")}</Badge>}
            </FieldLabel>
          </Field>
          <ul className="ml-7 flex flex-col gap-1 text-muted-foreground">
            {s.changes.map((c) => (
              <li key={c}>{c}</li>
            ))}
            {s.confirm.map((c) => (
              <li key={c} className="flex items-start gap-1.5 text-warning">
                <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                {c}
              </li>
            ))}
            {s.skipped.map((c) => (
              <li key={c}>{t("settings.share.skipped", { item: c })}</li>
            ))}
            {!s.changes.length && !s.confirm.length && !s.skipped.length && <li>{t("settings.share.noChanges")}</li>}
          </ul>
        </div>
      ))}
      {notes.map((n) => (
        <p key={n} className="text-muted-foreground">
          {n}
        </p>
      ))}
      {pv.needs_confirm && (
        <>
          <Separator />
          <Field orientation="horizontal">
            <Checkbox id="imp-trust" checked={trusted} onCheckedChange={(v) => onTrust(!!v)} data-testid="share-trust" />
            <FieldLabel htmlFor="imp-trust" className="font-normal">
              {t("settings.share.trust")}
            </FieldLabel>
          </Field>
        </>
      )}
    </div>
  )
}

function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [text, setText] = useState("")
  const [pv, setPv] = useState<Preview | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [trusted, setTrusted] = useState(false)
  const [checking, setChecking] = useState(false)
  const [applying, setApplying] = useState(false)
  const file = useRef<HTMLInputElement>(null)

  const check = async (source: string) => {
    setChecking(true)
    setPv(null)
    try {
      const res = await api<Preview>("config_import_preview", source)
      setPv(res)
      setTrusted(false)
      setPicked(res.ok ? res.sections.filter((s) => !s.provider_dependent).map((s) => s.id) : [])
    } catch (e) {
      setPv({ ok: false, error: errMsg(e), sections: [], unknown_sections: [], invalid: [] })
    } finally {
      setChecking(false)
    }
  }

  const apply = async () => {
    setApplying(true)
    try {
      const res = await api<ApplyReply>("config_import_apply", text, picked, trusted)
      const skipped = Object.values(res.skipped ?? {}).flat().length
      if (res.errors?.length) notify.warning(t("settings.share.appliedErrors"), res.errors.join("\n"))
      else notify.success(t("settings.share.applied"), skipped ? t("settings.share.skippedCount", { count: skipped }) : res.backup ? t("settings.share.backupSaved") : "")
      onOpenChange(false)
    } catch (e) {
      notify.error(t("settings.share.applyFailed"), errMsg(e))
    } finally {
      setApplying(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setPv(null)
          setText("")
        }
      }}
    >
      <DialogContent className="sm:max-w-2xl" data-testid="share-import-dialog">
        <DialogHeader>
          <DialogTitle>{t("settings.share.importTitle")}</DialogTitle>
          <DialogDescription>{t("settings.share.importDesc")}</DialogDescription>
        </DialogHeader>
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
          <Textarea
            data-testid="share-import-text"
            className="min-h-40 font-mono select-text"
            spellCheck={false}
            placeholder={t("settings.share.placeholder")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" data-testid="share-open-file" onClick={() => file.current?.click()}>
              <FolderOpenIcon data-icon="inline-start" />
              {t("settings.share.openFile")}
            </Button>
            <input
              ref={file}
              type="file"
              hidden
              accept=".chimera,.json,application/json,text/plain"
              data-testid="share-file-input"
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ""
                if (!f) return
                const r = new FileReader()
                r.onload = () => {
                  const s = String(r.result || "")
                  setText(s)
                  void check(s)
                }
                r.readAsText(f)
              }}
            />
            <Button variant="outline" size="sm" data-testid="share-check" disabled={checking || !text.trim()} onClick={() => void check(text)}>
              {checking ? <Spinner data-icon="inline-start" /> : <ScanSearchIcon data-icon="inline-start" />}
              {t("settings.share.check")}
            </Button>
          </div>
          {pv && (
            <PreviewView
              pv={pv}
              picked={picked}
              onPick={(id, on) => setPicked((cur) => (on ? [...cur, id] : cur.filter((x) => x !== id)))}
              trusted={trusted}
              onTrust={setTrusted}
            />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          <Button data-testid="share-apply" disabled={!pv?.ok || !picked.length || applying} onClick={() => void apply()}>
            {applying && <Spinner data-icon="inline-start" />}
            {t("settings.share.apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ShareCard() {
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  return (
    <Card data-testid="settings-share">
      <CardHeader>
        <CardTitleIcon icon={SendIcon}>{t("settings.share.title")}</CardTitleIcon>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <SettingRow title={t("settings.share.export")} hint={t("settings.share.exportHint")}>
            <Button variant="outline" size="sm" data-testid="settings-share-export" onClick={() => setExporting(true)}>
              <UploadIcon data-icon="inline-start" />
              {t("settings.share.exportButton")}
            </Button>
          </SettingRow>
          <SettingRow title={t("settings.share.import")} hint={t("settings.share.importHint")}>
            <Button variant="outline" size="sm" data-testid="settings-share-import" onClick={() => setImporting(true)}>
              <DownloadIcon data-icon="inline-start" />
              {t("settings.share.importButton")}
            </Button>
          </SettingRow>
        </FieldGroup>
      </CardContent>
      <ExportDialog open={exporting} onOpenChange={setExporting} />
      <ImportDialog open={importing} onOpenChange={setImporting} />
    </Card>
  )
}
