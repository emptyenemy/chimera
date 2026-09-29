/* Hosts → «Дополнительно»: автообновление IP, чекер записей, автопереключение
   провайдера и порядок переключения (фоновый поток modules/hosts/background.py). */

import { useState } from "react"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from "@/components/ui/input-group"
import { Item, ItemActions, ItemContent, ItemGroup } from "@/components/ui/item"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { optimistic } from "@/lib/store"
import type { Background, HostsView, Provider } from "@/pages/hosts-data"

const REFRESH_DEFAULT_H = 6 // часы — как DEFAULT_OPTIONS.refresh_interval у background.py
const CHECK_DEFAULT_M = 15 // минуты — как DEFAULT_OPTIONS.check_interval

function parseInterval(value: string, unitSeconds: number, defaultUnits: number): number {
  const s = value.trim()
  if (!s) return defaultUnits * unitSeconds
  const n = parseInt(s, 10)
  if (!Number.isFinite(n) || n <= 0) return defaultUnits * unitSeconds
  return n * unitSeconds
}

// Порядок из настроек может отставать от списка dns-провайдеров (добавили нового,
// удалили старого): недостающих довешиваем в конец, забытых убираем.
function effectiveOrder(bg: Background, dns: Provider[]): string[] {
  const known = new Set(dns.map((p) => p.id))
  const order = (bg.provider_order ?? []).filter((id) => known.has(id))
  for (const p of dns) if (!order.includes(p.id)) order.push(p.id)
  return order
}

// hosts_set_background отдаёт объект background целиком, а не обёрнутый в состояние:
// optimistic() слил бы его в корень ключа, поэтому applyResult: false, патчим сами.
function saveBackground(current: Background, patch: Partial<Background>) {
  return optimistic("hosts", { background: { ...current, ...patch } }, () => api("hosts_set_background", patch), {
    applyResult: false,
    errorTitle: t("hosts.bg.failed"),
  }).catch(() => {})
}

/** Число в поле с подписью единицы; сохраняется по уходу из поля или Enter. */
function IntervalInput({
  id,
  testid,
  value,
  placeholder,
  unit,
  onCommit,
}: {
  id: string
  testid: string
  value: number | ""
  placeholder: number
  unit: string
  onCommit: (raw: string) => void
}) {
  return (
    <InputGroup className="w-36">
      <InputGroupAddon>
        <InputGroupText>{t("hosts.bg.every")}</InputGroupText>
      </InputGroupAddon>
      <InputGroupInput
        // key: значение из стора обновилось снаружи — поле показывает новое
        key={value}
        id={id}
        data-testid={testid}
        className="text-center font-mono"
        type="text"
        inputMode="numeric"
        placeholder={String(placeholder)}
        defaultValue={value}
        onBlur={(e) => onCommit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur()
        }}
      />
      <InputGroupAddon align="inline-end">
        <InputGroupText>{unit}</InputGroupText>
      </InputGroupAddon>
    </InputGroup>
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
    void saveBackground(bg, { provider_order: next })
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
                    placeholder={REFRESH_DEFAULT_H}
                    unit={t("hosts.bg.hours")}
                    onCommit={(raw) =>
                      void saveBackground(bg, { refresh_interval: parseInterval(raw, 3600, REFRESH_DEFAULT_H) })
                    }
                  />
                  <Switch
                    id="hosts-refresh-switch"
                    data-testid="hosts-refresh-enabled"
                    checked={bg.refresh_enabled !== false}
                    onCheckedChange={(v) => void saveBackground(bg, { refresh_enabled: v })}
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
                    placeholder={CHECK_DEFAULT_M}
                    unit={t("hosts.bg.minutes")}
                    onCommit={(raw) =>
                      void saveBackground(bg, { check_interval: parseInterval(raw, 60, CHECK_DEFAULT_M) })
                    }
                  />
                  <Switch
                    id="hosts-check-switch"
                    data-testid="hosts-check-enabled"
                    checked={bg.check_enabled !== false}
                    onCheckedChange={(v) => void saveBackground(bg, { check_enabled: v })}
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
                    onCheckedChange={(v) => void saveBackground(bg, { autoswitch_enabled: v })}
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
