/* Стратегии — обход DPI: zapret2/winws2. Состояние — стор "winws" (хаб опрашивает его
   всегда) и "filters" (ленивый ключ, включаем на время показа). Список стратегий может
   быть длинным: поиск по имени/описанию, выбранная плитка подсвечена, а клик по плитке во
   время работы сразу переключает стратегию. */

import { useEffect, useState, type ComponentProps } from "react"
import {
  ArrowRightIcon,
  CircleAlertIcon,
  ListChecksIcon,
  ListIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  ShieldIcon,
  SlidersHorizontalIcon,
  TerminalIcon,
} from "lucide-react"
import { cn } from "cn"

import { TrialButton } from "@/components/app/trial"
import { Fold } from "@/components/app/fold"
import { LogView } from "@/components/app/log-view"
import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldTitle } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { useHubWatch } from "@/lib/hub-watch"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { optimistic, useStore } from "@/lib/store"
import { setTransport } from "@/pages/lists-data"
import type { AppInfo } from "@/lib/types"
import { commitRange, discardRange, editRange, flushRanges, resetRanges, reportFilterApply as reportApply, GAME_RANGE_DEFAULT, RANGE_DRAFTS_KEY, RANGE_RESET_KEY } from "@/pages/strategy-filters"
import type { FiltersState, GameMode, IpsetMode, Proto, RangeDrafts } from "@/pages/strategy-filters"

// --- данные --------------------------------------------------------------------

interface Strategy {
  id: string
  name?: string
  desc?: string
}

interface WinwsFull {
  running?: boolean
  external?: boolean
  current?: string | null
  last_strategy?: string | null
  autostart?: boolean
  lists?: string[]
  all_lists?: string[]
  windivert?: string | null
  strategies?: Strategy[]
  error?: string
}

const CUSTOM_FAKE = "__custom__" // псевдо-пункт «свой файл»: блоб в слоте подложили руками

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const wdLingers = (st: WinwsFull | undefined) => !!st && !st.running && st.windivert === "RUNNING"

// --- статус, пуск и остановка ------------------------------------------------------------

function StatusCard({
  st,
  selected,
  busy,
  onToggle,
}: {
  st: WinwsFull | undefined
  selected: string | null
  busy: boolean
  onToggle: () => void
}) {
  const app = useStore<AppInfo>("app")
  if (!st)
    return (
      <Card>
        <CardContent className="flex flex-col gap-2">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-6 w-1/3" />
        </CardContent>
      </Card>
    )
  const admin = app?.admin !== false
  const lingers = wdLingers(st)
  const on = !!st.running || lingers
  const stratName = st.strategies?.find((s) => s.id === (st.current || selected))?.name
  const title = st.external
    ? t("strat.status.external")
    : st.running
      ? t("strat.status.running", { name: stratName || st.current || "?" })
      : lingers
        ? t("strat.status.lingers")
        : t("strat.status.stopped")
  const label = lingers ? t("strat.unload") : st.running ? t("strat.stop") : t("strat.start")
  const noAdmin = !on && !admin
  const disabled = (!on && !selected) || noAdmin
  const tip = noAdmin ? t("strat.needAdmin") : !on && !selected ? t("strat.pickFirst") : ""

  return (
    <Card data-testid="strat-status" data-state={st.running ? "on" : "off"} className={cn(st.running && "ring-primary/40")}>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusDot tone={st.running ? "on" : lingers ? "warn" : "off"} />
          <div data-testid="strat-status-title" className="min-w-0 flex-1 truncate font-semibold">
            {title}
          </div>
          <Field orientation="horizontal" className="w-auto">
            <FieldLabel htmlFor="strat-autostart" className="font-normal text-muted-foreground">
              {t("strat.autostart")}
            </FieldLabel>
            <Switch
              id="strat-autostart"
              data-testid="strat-autostart"
              checked={!!st.autostart}
              onCheckedChange={(v) =>
                void optimistic("winws", { autostart: v }, () => api("winws_set_autostart", v), {
                  errorTitle: t("strat.autostart.failed"),
                }).catch(() => {})
              }
            />
          </Field>
          <TrialButton kind="strategy" target={selected ?? ""} disabled={!admin || !selected || busy || !!st.external} />
          <Tooltip>
            <TooltipTrigger render={<span />}>
              <Button
                size="sm"
                variant={on ? "destructive" : "default"}
                data-testid="strat-toggle"
                disabled={disabled || busy}
                onClick={onToggle}
              >
                {busy && <Spinner data-icon="inline-start" />}
                {label}
              </Button>
            </TooltipTrigger>
            {tip && !busy && <TooltipContent>{tip}</TooltipContent>}
          </Tooltip>
        </div>
        {st.error && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertDescription>{st.error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

// --- список стратегий -----------------------------------------------------------------------

// Плитка стратегии: только имя; что внутри (fake/split/…) — во всплывающей подсказке,
// пользователю это нужно разве что для сравнения, а не каждый раз перед глазами
function StrategyTile({ s, running, selected, onPick }: { s: Strategy; running: boolean; selected: boolean; onPick: (id: string) => void }) {
  const button = (
    <Button
      variant={selected ? "secondary" : "outline"}
      aria-pressed={selected}
      data-testid={`strat-tile-${s.id}`}
      data-running={running ? "true" : undefined}
      data-selected={selected ? "true" : undefined}
      className={cn("h-10 justify-start", running && "ring-1 ring-primary/60", selected && "ring-1 ring-foreground/40")}
      onClick={() => onPick(s.id)}
    >
      {running && <StatusDot tone="on" />}
      <span className="truncate">{s.name || s.id}</span>
    </Button>
  )
  if (!s.desc) return button
  return (
    <Tooltip>
      <TooltipTrigger render={button} />
      <TooltipContent className="max-w-sm">{s.desc}</TooltipContent>
    </Tooltip>
  )
}

function StrategyList({
  st,
  selected,
  search,
  onSearch,
  onPick,
}: {
  st: WinwsFull | undefined
  selected: string | null
  search: string
  onSearch: (v: string) => void
  onPick: (id: string) => void
}) {
  const q = search.trim().toLowerCase()
  const all = st?.strategies ?? []
  const list = q ? all.filter((s) => (s.name || s.id).toLowerCase().includes(q) || (s.desc || "").toLowerCase().includes(q)) : all
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <CardTitle className="flex items-center gap-2">
          <ListChecksIcon className="size-4" />
          {t("strat.list.title")}
        </CardTitle>
        <CardAction className="w-full @md/card-header:w-48">
          <InputGroup className="w-full">
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
            <InputGroupInput
              type="search"
              data-testid="strat-search"
              aria-label={t("strat.search")}
              placeholder={t("strat.search")}
              value={search}
              onChange={(e) => onSearch(e.target.value)}
            />
          </InputGroup>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!st ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : !all.length ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ShieldIcon />
              </EmptyMedia>
              <EmptyTitle>{t("strat.list.none")}</EmptyTitle>
              <EmptyDescription>{t("strat.list.noneDesc")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : !list.length ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SearchIcon />
              </EmptyMedia>
              <EmptyTitle>{t("strat.list.notFound")}</EmptyTitle>
              <EmptyDescription>{t("strat.list.notFoundDesc", { query: search })}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div data-testid="strat-grid" className="grid max-h-80 grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2 overflow-y-auto p-0.5">
            {list.map((s) => (
              <StrategyTile key={s.id} s={s} running={s.id === st.current} selected={s.id === selected} onPick={onPick} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// --- списки для маршрутизации через winws ----------------------------------------------------

function ListsCard({ st }: { st: WinwsFull | undefined }) {
  const all = st?.all_lists ?? []
  const chosen = new Set(st?.lists ?? [])
  const toggle = (name: string, on: boolean) => {
    void setTransport(name, "winws", on, { notifyInfo: false, errorTitle: t("strat.lists.failed") })
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListIcon className="size-4" />
          {t("strat.lists.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!st ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/3" />
          </div>
        ) : !all.length ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ListIcon />
              </EmptyMedia>
              <EmptyTitle>{t("strat.lists.none")}</EmptyTitle>
              <EmptyDescription>{t("strat.lists.noneDesc")}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button variant="outline" size="sm" data-testid="strat-go-lists" onClick={() => router.go("lists")}>
                {t("strat.lists.go")}
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <FieldGroup className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-4 gap-y-2">
            {all.map((name) => (
              <Field key={name} orientation="horizontal">
                <Checkbox
                  id={`strat-list-${name}`}
                  data-testid={`strat-list-${name}`}
                  checked={chosen.has(name)}
                  onCheckedChange={(v) => toggle(name, v === true)}
                />
                <FieldLabel htmlFor={`strat-list-${name}`} className="font-normal">
                  {name}
                </FieldLabel>
              </Field>
            ))}
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

// --- фильтры (game / ipset / fake) ------------------------------------------------------------------

// выбранный сегмент — основным цветом: стандартная подсветка outline-переключателя в тёмной теме еле видна
function Segment(props: ComponentProps<typeof ToggleGroupItem>) {
  return <ToggleGroupItem className="aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary/90" {...props} />
}

function GameRanges({ f }: { f: FiltersState }) {
  const ranges = f.game_ranges ?? { tcp: GAME_RANGE_DEFAULT, udp: GAME_RANGE_DEFAULT }
  const draft = useStore<RangeDrafts>(RANGE_DRAFTS_KEY) ?? {}
  const resetting = useStore<boolean>(RANGE_RESET_KEY) ?? false
  useEffect(() => () => { void flushRanges() }, [])

  const field = (which: Proto, enabled: boolean) => {
    const err = draft[which]?.error
    return (
      <Field key={which} data-invalid={err ? true : undefined} data-disabled={enabled ? undefined : true} className="w-48">
        <FieldLabel htmlFor={`strat-range-${which}`} className="font-normal text-muted-foreground">
          {t(which === "tcp" ? "strat.range.tcp" : "strat.range.udp")}
        </FieldLabel>
        <Input
          id={`strat-range-${which}`}
          data-testid={`strat-range-${which}`}
          className="font-mono"
          spellCheck={false}
          disabled={!enabled}
          aria-invalid={err ? true : undefined}
          aria-describedby={err ? `strat-range-${which}-error` : undefined}
          value={draft[which]?.value ?? ranges[which] ?? ""}
          onChange={(e) => editRange(which, e.target.value)}
          onBlur={() => void commitRange(which)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur()
            if (e.key === "Escape") {
              e.preventDefault()
              discardRange(which)
            }
          }}
        />
        {err && <FieldError id={`strat-range-${which}-error`} data-testid={`strat-range-${which}-error`}>{err}</FieldError>}
      </Field>
    )
  }

  return (
    <div className="flex flex-wrap items-start gap-3">
      {field("tcp", f.game === "all" || f.game === "tcp")}
      {field("udp", f.game === "all" || f.game === "udp")}
      <Button variant="outline" size="sm" className="self-end" data-testid="strat-range-default" disabled={resetting} onClick={() => void resetRanges()}>
        <RotateCcwIcon data-icon="inline-start" />
        {t("strat.range.default")}
      </Button>
    </div>
  )
}

function FiltersBlock({ f }: { f: FiltersState | undefined }) {
  const [updating, setUpdating] = useState(false)
  if (!f)
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    )

  const setGame = async (mode: GameMode) => {
    let res: FiltersState
    try {
      res = await optimistic("filters", { game: mode }, () => api<FiltersState>("game_filter_set", mode), { errorTitle: t("strat.game.failed") })
    } catch {
      return
    }
    reportApply(t("strat.game.label"), res)
  }

  // winws2 сам перечитывает ipset при изменении файла — перезапуск не нужен
  const setIpset = (mode: IpsetMode) =>
    void optimistic("filters", { ipset: mode }, () => api("ipset_set", mode), { errorTitle: t("strat.ipset.failed") }).catch(() => {})

  const updateIpset = async () => {
    if (updating) return
    setUpdating(true)
    try {
      const r = await api<{ downloaded: number }>("ipset_update")
      notify.success(t("strat.ipset.updated"), t("strat.ipset.stored", { count: r.downloaded, n: fmtNum(r.downloaded) }))
    } catch (e) {
      notify.error(t("strat.ipset.updateFailed"), errText(e))
    } finally {
      setUpdating(false)
    }
  }

  const setFake = async (slot: string, name: string) => {
    if (name === CUSTOM_FAKE) return
    let res: FiltersState
    try {
      res = await optimistic("filters", null, () => api<FiltersState>("fake_set", slot, name), { errorTitle: t("strat.fake.failed") })
    } catch {
      return
    }
    reportApply(t("strat.fake.label"), res)
  }

  const ipsetNote =
    f.ipset === "loaded"
      ? t("strat.ipset.subnets", { count: f.ipset_count ?? 0, n: fmtNum(f.ipset_count ?? 0) })
      : f.ipset_stored
        ? t("strat.ipset.inStore", { n: fmtNum(f.ipset_stored) })
        : ""
  const fakes = f.fakes

  return (
    <FieldGroup className="gap-4">
      <div className="flex flex-col gap-3" data-testid="strat-game">
        <Field orientation="horizontal" className="flex-wrap justify-between">
          <FieldTitle id="strat-game-label">{t("strat.game.title")}</FieldTitle>
          <ToggleGroup
            variant="outline"
            size="sm"
            aria-labelledby="strat-game-label"
            value={[f.game]}
            onValueChange={(v) => v[0] && void setGame(v[0] as GameMode)}
          >
            <Segment value="off" data-testid="strat-game-off">{t("strat.game.off")}</Segment>
            <Segment value="all" data-testid="strat-game-all">TCP+UDP</Segment>
            <Segment value="tcp" data-testid="strat-game-tcp">TCP</Segment>
            <Segment value="udp" data-testid="strat-game-udp">UDP</Segment>
          </ToggleGroup>
        </Field>
        {f.game !== "off" && <GameRanges f={f} />}
      </div>
      <Separator />
      <Field orientation="horizontal" className="flex-wrap justify-between" data-testid="strat-ipset">
        <FieldTitle id="strat-ipset-label">
          {t("strat.ipset.title")}
          {ipsetNote && <span className="font-normal text-muted-foreground"> · {ipsetNote}</span>}
        </FieldTitle>
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            variant="outline"
            size="sm"
            aria-labelledby="strat-ipset-label"
            value={[f.ipset]}
            onValueChange={(v) => v[0] && setIpset(v[0] as IpsetMode)}
          >
            <Segment value="none" data-testid="strat-ipset-none">{t("strat.ipset.none")}</Segment>
            <Segment value="any" data-testid="strat-ipset-any">{t("strat.ipset.any")}</Segment>
            <Segment value="loaded" data-testid="strat-ipset-loaded">{t("strat.ipset.loaded")}</Segment>
          </ToggleGroup>
          <Button variant="outline" size="sm" data-testid="strat-ipset-update" disabled={updating} onClick={() => void updateIpset()}>
            {updating ? <Spinner data-icon="inline-start" /> : <RefreshCwIcon data-icon="inline-start" />}
            {t("strat.ipset.update")}
          </Button>
        </div>
      </Field>
      <Separator />
      {!fakes || !fakes.candidates?.length ? (
        <FieldDescription>{t("strat.fake.none")}</FieldDescription>
      ) : (
        <div data-testid="strat-fakes" className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
          {Object.entries(fakes.slots).map(([slot, s]) => {
            const items = [
              ...(s.present && !s.current ? [{ label: t("strat.fake.custom"), value: CUSTOM_FAKE }] : []),
              ...fakes.candidates.map((name) => ({ label: name, value: name })),
            ]
            return (
              <Field key={slot}>
                <FieldLabel htmlFor={`strat-fake-${slot}`}>{s.label}</FieldLabel>
                <Select items={items} value={s.current ?? (s.present ? CUSTOM_FAKE : null)} onValueChange={(v) => v && void setFake(slot, v)}>
                  <SelectTrigger id={`strat-fake-${slot}`} data-testid={`strat-fake-${slot}`} size="sm" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent alignItemWithTrigger={false}>
                    <SelectGroup>
                      {items.map((it) => (
                        <SelectItem key={it.value} value={it.value} data-testid={`strat-fake-${slot}-${it.value}`}>
                          {it.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            )
          })}
        </div>
      )}
    </FieldGroup>
  )
}

// --- страница ------------------------------------------------------------------------------------------

export function StrategiesPage() {
  useHubWatch(["filters"])
  const st = useStore<WinwsFull>("winws")
  const filters = useStore<FiltersState>("filters")
  const [picked, setPicked] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [busy, setBusy] = useState<"toggle" | "switch" | null>(null)

  // запущенная стратегия важнее выбора; пока стоим — выбранная, потом последняя, потом первая
  const selected = st ? st.current || picked || st.last_strategy || st.strategies?.[0]?.id || null : null

  const toggle = async () => {
    if (busy || !st) return
    const lingers = wdLingers(st)
    setBusy("toggle")
    try {
      if (st.running || lingers) {
        await optimistic("winws", { running: false, current: null }, () => api("winws_stop"), { errorTitle: t("strat.stop.failed") })
        notify.success(t(lingers ? "strat.stop.driver" : "strat.stop.done"))
      } else {
        if (!selected) return
        await optimistic("winws", { running: true, current: selected }, () => api("winws_start", selected), { errorTitle: t("strat.start.failed") })
        notify.success(t("strat.start.done"))
      }
    } catch {
      /* тост уже показан optimistic() */
    } finally {
      setBusy(null)
    }
  }

  const pick = async (id: string) => {
    if (busy || !st) return
    setPicked(id)
    if (st.running && id !== st.current) {
      setBusy("switch")
      try {
        await optimistic("winws", { current: id, running: true }, () => api("winws_start", id), { errorTitle: t("strat.switch.failed") })
        notify.success(t("strat.switch.done"))
      } catch {
        /* тост уже показан */
      } finally {
        setBusy(null)
      }
    }
  }

  return (
    <Page id="strategies" title={t("nav.strategies")}>
      <StatusCard st={st} selected={selected} busy={busy === "toggle"} onToggle={() => void toggle()} />
      <StrategyList st={st} selected={selected} search={search} onSearch={setSearch} onPick={(id) => void pick(id)} />
      <ListsCard st={st} />
      <Fold icon={SlidersHorizontalIcon} title={t("strat.advanced")} testId="strat-advanced">
        <FiltersBlock f={filters} />
      </Fold>
      <Fold icon={TerminalIcon} title={t("strat.logs")} testId="strat-logs">
        <LogView method="winws_log" />
      </Fold>
    </Page>
  )
}
