/* Hosts → «Дополнительно»: автообновление IP, чекер записей, автопереключение
   провайдера и порядок переключения (фоновый поток modules/hosts/background.py). */

import { useRef, useState } from "react"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldContent, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from "@/components/ui/input-group"
import { Item, ItemActions, ItemContent, ItemGroup } from "@/components/ui/item"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { parseInterval } from "@/lib/interval"
import { optimistic } from "@/lib/store"
import type { Background, HostsView, Provider } from "@/pages/hosts-data"

const REFRESH_DEFAULT_H = 6 // часы — как DEFAULT_OPTIONS.refresh_interval у background.py
const CHECK_DEFAULT_M = 15 // минуты — как DEFAULT_OPTIONS.check_interval

// Порядок из настроек может отставать от списка dns-провайдеров (добавили нового,
// удалили старого): недостающих довешиваем в конец, забытых убираем.
function effectiveOrder(bg: Background, dns: Provider[]): string[] {
  const known = new Set(dns.map((p) => p.id))
  const order = (bg.provider_order ?? []).filter((id) => known.has(id))
  for (const p of dns) if (!order.includes(p.id)) order.push(p.id)
  return order
}

function saveBackground(patch: Partial<Background>) {
  return optimistic("hosts", (value) => ({
    background: { ...(value as HostsView | undefined)?.background, ...patch },
  }), async () => ({ background: await api<Background>("hosts_set_background", patch) }), {
    errorTitle: t("hosts.bg.failed"),
  }).then(() => true, () => false)
}

/** Число в поле с подписью единицы; сохраняется по уходу из поля или Enter. */
function IntervalInput({
  id,
  testid,
  value,
  placeholder,
  unit,
  unitSeconds,
  label,
  onCommit,
}: {
  id: string
  testid: string
  value: number | ""
  placeholder: number
  unit: string
  unitSeconds: number
  label: string
  onCommit: (seconds: number) => Promise<boolean>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<"invalid" | "save" | null>(null)
  const dirty = useRef(false)
  const revision = useRef(0)
  const commit = (raw: string) => {
    if (!dirty.current) return
    const seconds = parseInterval(raw, unitSeconds, placeholder)
    if (seconds === null) {
      setError("invalid")
      return
    }
    const submitted = revision.current
    dirty.current = false
    setError(null)
    void onCommit(seconds).then((ok) => {
      if (revision.current !== submitted) return
      if (ok) setDraft(null)
      else {
        dirty.current = true
        setError("save")
      }
    })
  }
  return (
    <Field className="w-36 gap-1" data-invalid={!!error}>
      <InputGroup className="w-36">
        <InputGroupAddon>
          <InputGroupText>{t("hosts.bg.every")}</InputGroupText>
        </InputGroupAddon>
        <InputGroupInput
          id={id}
          data-testid={testid}
          className="text-center font-mono"
          type="text"
          inputMode="numeric"
          placeholder={String(placeholder)}
          value={draft ?? value}
          aria-label={`${label}, ${t("hosts.bg.every")} (${unit})`}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => {
            setDraft(e.target.value)
            dirty.current = true
            revision.current += 1
            setError(null)
          }}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur()
            if (e.key === "Escape") {
              e.preventDefault()
              setDraft(null)
              dirty.current = false
              revision.current += 1
              setError(null)
            }
          }}
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText>{unit}</InputGroupText>
        </InputGroupAddon>
      </InputGroup>
      {error && <FieldError id={`${id}-error`} data-testid={`${testid}-error`}>
        {t(error === "invalid" ? "hosts.bg.invalidInterval" : "hosts.bg.failed")}
      </FieldError>}
    </Field>
  )
}

export function AdvancedCard({ st, providers }: { st: HostsView; providers: Provider[] | undefined }) {
  const [open, setOpen] = useState(false)
  const bg = st.background ?? {}
  const dns = (providers ?? []).filter((p) => p.type === "dns")
  const order = effectiveOrder(bg, dns)
  const nameOf = (id: string) => providers?.find((p) => p.id === id)?.name || id
  const refreshH = bg.refresh_interval ? Math.round(bg.refresh_interval / 3600) : ""
  const checkM = bg.check_interval ? Math.round(bg.check_interval / 60) : ""

  const move = (id: string, dir: -1 | 1) => {
    const next = [...order]
    const i = next.indexOf(id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    void saveBackground({ provider_order: next })
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card size="sm" data-testid="hosts-advanced">
        <CardHeader>
          <CollapsibleTrigger
            render={<Button variant="ghost" className="w-full justify-between" data-testid="hosts-advanced-toggle" />}
          >
            {t("hosts.bg.title")}
            <ChevronDownIcon data-icon="inline-end" className={open ? "rotate-180" : undefined} />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent>
            {!providers ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : (
              <FieldGroup className="gap-4">
                <Field orientation="horizontal" className="flex-wrap">
                  <FieldLabel htmlFor="hosts-refresh-switch" className="min-w-40">
                    {t("hosts.bg.refresh")}
                  </FieldLabel>
                  <IntervalInput
                    id="hosts-refresh-h"
                    testid="hosts-refresh-interval"
                    value={refreshH}
                    unitSeconds={3600}
                    label={t("hosts.bg.refresh")}
                    placeholder={REFRESH_DEFAULT_H}
                    unit={t("hosts.bg.hours")}
                    onCommit={(seconds) => saveBackground({ refresh_interval: seconds })}
                  />
                  <Switch
                    id="hosts-refresh-switch"
                    data-testid="hosts-refresh-enabled"
                    checked={bg.refresh_enabled !== false}
                    onCheckedChange={(v) => void saveBackground({ refresh_enabled: v })}
                  />
                </Field>
                <Field orientation="horizontal" className="flex-wrap">
                  <FieldLabel htmlFor="hosts-check-switch" className="min-w-40">
                    {t("hosts.bg.check")}
                  </FieldLabel>
                  <IntervalInput
                    id="hosts-check-m"
                    testid="hosts-check-interval"
                    value={checkM}
                    unitSeconds={60}
                    label={t("hosts.bg.check")}
                    placeholder={CHECK_DEFAULT_M}
                    unit={t("hosts.bg.minutes")}
                    onCommit={(seconds) => saveBackground({ check_interval: seconds })}
                  />
                  <Switch
                    id="hosts-check-switch"
                    data-testid="hosts-check-enabled"
                    checked={bg.check_enabled !== false}
                    onCheckedChange={(v) => void saveBackground({ check_enabled: v })}
                  />
                </Field>
                <Separator />
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="hosts-autoswitch">{t("hosts.bg.autoswitch")}</FieldLabel>
                    <FieldDescription>{t("hosts.bg.autoswitchDesc")}</FieldDescription>
                  </FieldContent>
                  <Switch
                    id="hosts-autoswitch"
                    data-testid="hosts-autoswitch"
                    checked={!!bg.autoswitch_enabled}
                    onCheckedChange={(v) => void saveBackground({ autoswitch_enabled: v })}
                  />
                </Field>
                {bg.autoswitch_enabled &&
                  (order.length ? (
                    <ItemGroup className="gap-2" data-testid="hosts-order">
                      {order.map((id, i) => (
                        <Item key={id} variant="outline" size="xs" data-testid={`hosts-order-${id}`}>
                          <span className="w-5 text-right text-muted-foreground tabular-nums">{i + 1}</span>
                          <ItemContent>{nameOf(id)}</ItemContent>
                          <ItemActions>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              disabled={i === 0}
                              aria-label={t("hosts.bg.up")}
                              title={t("hosts.bg.up")}
                              data-testid={`hosts-order-up-${id}`}
                              onClick={() => move(id, -1)}
                            >
                              <ChevronUpIcon />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              disabled={i === order.length - 1}
                              aria-label={t("hosts.bg.down")}
                              title={t("hosts.bg.down")}
                              data-testid={`hosts-order-down-${id}`}
                              onClick={() => move(id, 1)}
                            >
                              <ChevronDownIcon />
                            </Button>
                          </ItemActions>
                        </Item>
                      ))}
                    </ItemGroup>
                  ) : (
                    <FieldDescription>{t("hosts.bg.noOrder")}</FieldDescription>
                  ))}
              </FieldGroup>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
