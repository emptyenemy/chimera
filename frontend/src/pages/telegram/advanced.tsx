/* Продвинутые настройки ядра (CF-proxy/worker домены, Fake TLS, подмена IP дата-центров).
   Ядро читает их только при старте, поэтому запущенный прокси перезапускается сам (Api);
   сбой перезапуска приезжает в apply_error. */

import { ChevronDownIcon, PlusIcon, SlidersHorizontalIcon, TriangleAlertIcon, XIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store, useStore } from "@/lib/store"
import { useDebounced, useDraft } from "@/lib/use-autosave"
import type { TgFull } from "@/pages/telegram/types"

type SwitchKey = "disable_secure" | "fallback_cfproxy" | "proxy_protocol" | "force_test_dc"

interface TextDraft {
  cfproxy_user_domains: string
  cfproxy_worker_domains: string
  fake_tls_domain: string
  dc: [string, string][]
}

const SWITCHES: { key: SwitchKey; on: (st: TgFull) => boolean }[] = [
  { key: "disable_secure", on: (st) => !!st.disable_secure },
  { key: "fallback_cfproxy", on: (st) => st.fallback_cfproxy !== false },
]
const SWITCHES_TAIL: { key: SwitchKey; on: (st: TgFull) => boolean }[] = [
  { key: "proxy_protocol", on: (st) => !!st.proxy_protocol },
  { key: "force_test_dc", on: (st) => !!st.force_test_dc },
]

function fromState(st: TgFull, part: Partial<TextDraft> | null): TextDraft {
  return {
    cfproxy_user_domains: part?.cfproxy_user_domains ?? (st.cfproxy_user_domains ?? []).join("\n"),
    cfproxy_worker_domains: part?.cfproxy_worker_domains ?? (st.cfproxy_worker_domains ?? []).join("\n"),
    fake_tls_domain: part?.fake_tls_domain ?? st.fake_tls_domain ?? "",
    dc: part?.dc ?? Object.entries(st.dc_redirects ?? {}),
  }
}

async function toggleSwitch(key: SwitchKey, target: boolean) {
  try {
    await optimistic(
      "tg",
      { [key]: target },
      async () => {
        const res = await api<TgFull>("tg_set_advanced", { [key]: target })
        if (res?.apply_error) notify.error(t("tg.adv.applyFailed"), res.apply_error)
        return res
      },
      { errorTitle: t("tg.adv.saveFailed") }
    )
  } catch {
    /* тост уже показан */
  }
}

function SwitchRow({ st, item }: { st: TgFull; item: { key: SwitchKey; on: (st: TgFull) => boolean } }) {
  const id = `tg-adv-${item.key}`
  return (
    <Field orientation="horizontal">
      <FieldContent>
        <FieldLabel htmlFor={id}>{t(`tg.adv.${item.key}`)}</FieldLabel>
        <FieldDescription>{t(`tg.adv.${item.key}.hint`)}</FieldDescription>
      </FieldContent>
      <Switch id={id} data-testid={`tg-adv-switch-${item.key}`} checked={item.on(st)} onCheckedChange={(v) => void toggleSwitch(item.key, v)} />
    </Field>
  )
}

export function TgAdvanced() {
  const st = useStore<TgFull>("tg")
  const draft = useDraft<TextDraft>()

  const save = async () => {
    const cur = store.get<TgFull>("tg")
    const snap = draft.read()
    if (!cur || !snap) return
    const text = fromState(cur, snap)
    const dc: Record<string, string> = {}
    for (const [num, ip] of text.dc) if (num.trim() && ip.trim()) dc[num.trim()] = ip.trim()
    try {
      const res = await api<TgFull>("tg_set_advanced", {
        cfproxy_user_domains: text.cfproxy_user_domains,
        cfproxy_worker_domains: text.cfproxy_worker_domains,
        fake_tls_domain: text.fake_tls_domain,
        dc_redirects: dc,
      })
      if (!res || typeof res !== "object") return // бэкенд не подтвердил — черновик остаётся
      store.patch("tg", res)
      if (res.apply_error) notify.error(t("tg.adv.applyFailed"), res.apply_error)
      draft.clearIf(snap)
    } catch (e) {
      notify.error(t("tg.adv.saveFailed"), e instanceof Error ? e.message : String(e))
    }
  }
  const { schedule, flush } = useDebounced(() => void save())

  if (!st) return null
  const text = fromState(st, draft.value)
  const edit = (part: Partial<TextDraft>) => {
    // черновик строится от актуального состояния: правка одного поля не теряет остальные
    draft.update({ ...fromState(st, draft.read()), ...part })
    schedule()
  }
  const setDc = (i: number, col: 0 | 1, v: string) => {
    const rows = text.dc.map((r) => [...r] as [string, string])
    rows[i][col] = v
    edit({ dc: rows })
  }

  return (
    <Collapsible>
      <Card data-testid="tg-advanced" onBlur={flush}>
        <CollapsibleTrigger
          data-testid="tg-advanced-toggle"
          className="group/trigger w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SlidersHorizontalIcon className="size-4 text-muted-foreground" />
              {t("tg.adv.title")}
              <ChevronDownIcon className="ml-auto size-4 text-muted-foreground transition-transform group-data-[panel-open]/trigger:rotate-180" />
            </CardTitle>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent>
            <FieldGroup>
              {SWITCHES.map((item) => (
                <SwitchRow key={item.key} st={st} item={item} />
              ))}
              <Field>
                <FieldLabel htmlFor="tg-adv-user-domains">{t("tg.adv.userDomains")}</FieldLabel>
                <Textarea
                  id="tg-adv-user-domains"
                  data-testid="tg-adv-user-domains"
                  className="font-mono"
                  rows={3}
                  placeholder="example.com"
                  value={text.cfproxy_user_domains}
                  onChange={(e) => edit({ cfproxy_user_domains: e.target.value })}
                />
                <FieldDescription>{t("tg.adv.userDomains.hint")}</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="tg-adv-worker-domains">{t("tg.adv.workerDomains")}</FieldLabel>
                <Textarea
                  id="tg-adv-worker-domains"
                  data-testid="tg-adv-worker-domains"
                  className="font-mono"
                  rows={3}
                  placeholder="worker.example.com"
                  value={text.cfproxy_worker_domains}
                  onChange={(e) => edit({ cfproxy_worker_domains: e.target.value })}
                />
                <FieldDescription>{t("tg.adv.workerDomains.hint")}</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="tg-adv-fake-tls">{t("tg.adv.fakeTls")}</FieldLabel>
                <Input
                  id="tg-adv-fake-tls"
                  data-testid="tg-adv-fake-tls"
                  className="font-mono"
                  spellCheck={false}
                  placeholder="www.example.com"
                  value={text.fake_tls_domain}
                  onChange={(e) => edit({ fake_tls_domain: e.target.value })}
                  onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                />
                <FieldDescription>{t("tg.adv.fakeTls.hint")}</FieldDescription>
              </Field>
              <Field>
                <FieldLabel>{t("tg.adv.dc")}</FieldLabel>
                <FieldDescription>{t("tg.adv.dc.hint")}</FieldDescription>
                <div className="flex flex-col gap-2" data-testid="tg-dc-list">
                  {text.dc.map(([num, ip], i) => (
                    <div key={i} className="flex items-center gap-2" data-testid={`tg-dc-row-${i}`}>
                      <Input
                        className="w-20 shrink-0 font-mono"
                        aria-label={t("tg.adv.dc.num")}
                        placeholder={t("tg.adv.dc.num")}
                        value={num}
                        onChange={(e) => setDc(i, 0, e.target.value)}
                      />
                      <Input
                        className="min-w-0 flex-1 font-mono"
                        aria-label={t("tg.adv.dc.ip")}
                        placeholder={t("tg.adv.dc.ip")}
                        spellCheck={false}
                        value={ip}
                        onChange={(e) => setDc(i, 1, e.target.value)}
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        data-testid={`tg-dc-remove-${i}`}
                        aria-label={t("tg.adv.dc.remove")}
                        onClick={() => edit({ dc: text.dc.filter((_, j) => j !== i) })}
                      >
                        <XIcon />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-fit"
                    data-testid="tg-dc-add"
                    onClick={() => draft.update({ ...fromState(st, draft.read()), dc: [...text.dc, ["", ""]] })}
                  >
                    <PlusIcon data-icon="inline-start" />
                    {t("tg.adv.dc.add")}
                  </Button>
                </div>
              </Field>
              {SWITCHES_TAIL.map((item) => (
                <SwitchRow key={item.key} st={st} item={item} />
              ))}
              {st.running && (
                <Alert className="text-warning">
                  <TriangleAlertIcon />
                  <AlertDescription>{t("tg.adv.restartHint")}</AlertDescription>
                </Alert>
              )}
            </FieldGroup>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
