/* Проверка: одно поле — один ответ по каждому сайту. Внутри две проверки идут
   параллельно — есть ли сайт в реестре РКН (cheburcheck) и открывается ли он прямо сейчас
   с этой машины с учётом обхода (blockcheck), — а в таблице они сведены в итог словами:
   «Открывается», «Работает через обход», «Заблокирован» и т.п.

   Поле заодно и поиск: по набранному предлагаются списки, где такой домен есть, и сами
   домены — выбор подсказки запускает проверку списка или сайта.

   Здесь только отрисовка; разбор ввода, подсказки и состояние проверки — pages/checks-data.ts.
   Строки таблицы мемоизированы: результаты списка приходят пушами сотнями в секунду. */

import { memo, useEffect, useMemo, useRef, useState } from "react"
import { Autocomplete } from "@base-ui/react/autocomplete"
import { CircleCheckIcon, GlobeIcon, ListIcon, SearchIcon, TriangleAlertIcon } from "lucide-react"
import { cn } from "cn"

import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import {
  s,
  emit,
  useView,
  query,
  suggest,
  suggestionText,
  inRegistry,
  ipInRegistry,
  verdict,
  isProblem,
  checkTyped,
  loadLists,
  pickSuggestion,
  loadRegistryStatus,
  type RknResult,
  type Row,
  type View,
  type Suggestion,
  type SuggestionGroup,
  type Tone,
} from "@/pages/checks-data"

// --- отображение -------------------------------------------------------------------------

const DOT_TONE = { success: "ok", danger: "err", warning: "warn", muted: "off" } as const
const TEXT_TONE: Record<Tone, string> = {
  success: "",
  danger: "text-destructive",
  warning: "text-warning",
  muted: "text-muted-foreground",
}

function RegistryCell({ rkn, down }: { rkn: RknResult | null; down: boolean }) {
  if (!rkn) return <span className="text-muted-foreground">{down ? "—" : "…"}</span>
  if (rkn.status === "rate" || rkn.status === "error")
    return (
      <Tooltip>
        <TooltipTrigger render={<span className="text-muted-foreground" />}>—</TooltipTrigger>
        <TooltipContent>{t("checks.reg.noAnswer")}</TooltipContent>
      </Tooltip>
    )
  if (inRegistry(rkn)) return <Badge variant="secondary">{t("checks.reg.domain")}</Badge>
  if (ipInRegistry(rkn)) {
    const nets = [...(rkn.subnets ?? []), ...(rkn.cdn ?? [])].join(", ")
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="outline" />}>{t("checks.reg.ip")}</TooltipTrigger>
        {nets && <TooltipContent>{nets}</TooltipContent>}
      </Tooltip>
    )
  }
  return <span className="text-muted-foreground">{t("checks.reg.none")}</span>
}

const SiteRow = memo(function SiteRow({ site, row, down }: { site: string; row: Row; down: boolean }) {
  const v = verdict(row.rkn, row.reach)
  const reach = row.reach
  const ms = reach?.ms != null && (reach.status === "ok" || reach.status === "challenge") ? t("checks.ms", { ms: fmtNum(reach.ms) }) : ""
  return (
    <TableRow data-testid={`checks-row-${site}`} data-tone={v.tone}>
      <TableCell className="align-top font-mono text-[13px]">
        {reach?.ip ? (
          <Tooltip>
            <TooltipTrigger render={<span />}>{site}</TooltipTrigger>
            <TooltipContent>{t("checks.ip", { ip: reach.ip })}</TooltipContent>
          </Tooltip>
        ) : (
          site
        )}
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        <div className={cn("flex items-center gap-2 font-medium", TEXT_TONE[v.tone])}>
          {v.pending ? <Spinner className="size-3" /> : <StatusDot tone={DOT_TONE[v.tone]} />}
          {v.label}
        </div>
        {v.note && <div className="mt-0.5 pl-4 text-xs text-muted-foreground">{v.note}</div>}
      </TableCell>
      <TableCell className="align-top">
        <RegistryCell rkn={row.rkn} down={down} />
      </TableCell>
      <TableCell className="align-top text-right text-muted-foreground tabular-nums">{ms}</TableCell>
    </TableRow>
  )
})

function Summary({ view }: { view: View }) {
  const { run, results } = view
  if (run) return <span>{t("checks.summary.running", { done: Math.min(run.reachDone, run.total), total: run.total })}</span>
  const all = [...results.values()]
  if (!all.length) return null
  const open = all.filter((r) => verdict(r.rkn, r.reach).tone === "success").length
  const reg = all.filter((r) => inRegistry(r.rkn)).length
  return (
    <span data-testid="checks-summary">
      {t("checks.summary.open")} <b className="font-semibold text-foreground">{t("checks.summary.ofTotal", { n: open, total: all.length })}</b>
      {reg > 0 && (
        <>
          {" · "}
          {t("checks.summary.registry")} <b className="font-semibold text-foreground">{reg}</b>
        </>
      )}
    </span>
  )
}

function Results({ view }: { view: View }) {
  const { results, run, onlyProblems, registryDown } = view
  const rows = [...results.entries()].filter(([, r]) => !onlyProblems || isProblem(r))
  const progress = run && run.total ? Math.min(100, ((run.rknDone + run.reachDone) / (run.total * 2)) * 100) : 0
  return (
    <Card data-testid="checks-results">
      <CardHeader>
        <CardTitle className="font-normal text-muted-foreground">
          <Summary view={view} />
        </CardTitle>
        <CardAction>
          <Field orientation="horizontal">
            <Checkbox
              id="checks-only-problems"
              data-testid="checks-only-problems"
              checked={onlyProblems}
              onCheckedChange={(v) => {
                s.onlyProblems = v === true
                emit()
              }}
            />
            <FieldLabel htmlFor="checks-only-problems" className="font-normal">
              {t("checks.onlyProblems")}
            </FieldLabel>
          </Field>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {run && <Progress value={progress} data-testid="checks-progress" />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("checks.col.site")}</TableHead>
              <TableHead>{t("checks.col.verdict")}</TableHead>
              <TableHead>{t("checks.col.registry")}</TableHead>
              <TableHead className="text-right">{t("checks.col.answer")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([site, row]) => (
              <SiteRow key={site} site={site} row={row} down={!!registryDown} />
            ))}
            {!rows.length && run && (
              <TableRow>
                <TableCell colSpan={4}>
                  <div className="flex flex-col gap-2">
                    <Skeleton className="h-5 w-full" />
                    <Skeleton className="h-5 w-full" />
                    <Skeleton className="h-5 w-full" />
                  </div>
                </TableCell>
              </TableRow>
            )}
            {!rows.length && !run && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={4}>
                  <Empty className="p-6">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <CircleCheckIcon />
                      </EmptyMedia>
                      <EmptyTitle>{t("checks.empty.noProblems")}</EmptyTitle>
                    </EmptyHeader>
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// совпавшая с запросом часть — жирным
function Match({ text, q }: { text: string; q: string }) {
  const i = q ? text.toLowerCase().indexOf(q) : -1
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <b className="font-semibold text-foreground">{text.slice(i, i + q.length)}</b>
      {text.slice(i + q.length)}
    </>
  )
}

function SuggestionBody({ it, q }: { it: Suggestion; q: string }) {
  if (it.kind === "site")
    return (
      <>
        <GlobeIcon className="text-muted-foreground" />
        <span className="truncate font-mono text-[13px] text-muted-foreground">
          <Match text={it.domain} q={q} />
        </span>
      </>
    )
  const more = it.hits.length - 3
  return (
    <>
      <ListIcon className="mt-0.5 self-start text-muted-foreground" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-baseline gap-2">
          <span className="font-medium">
            <Match text={it.name} q={q} />
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">{fmtNum(it.count)}</span>
        </span>
        {it.hits.length > 0 && (
          <span className="truncate text-xs text-muted-foreground">
            {it.hits.slice(0, 3).join(", ")}
            {more > 0 && ` +${fmtNum(more)}`}
          </span>
        )}
      </div>
    </>
  )
}

function CheckForm({ view }: { view: View }) {
  const { run, input, lists, registryDown } = view
  const groups = useMemo(() => suggest(lists, input), [lists, input])
  const [open, setOpen] = useState(false)
  const highlighted = useRef<Suggestion | undefined>(undefined)
  const anchor = useRef<HTMLDivElement>(null)
  const shown = open && groups.length > 0 && !run
  const q = query(input)
  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <Autocomplete.Root
          items={groups}
          filter={null}
          value={input}
          open={shown}
          itemToStringValue={suggestionText}
          onOpenChange={(next) => {
            setOpen(next)
            if (!next) highlighted.current = undefined
          }}
          onItemHighlighted={(it) => {
            highlighted.current = it
          }}
          onValueChange={(value, details) => {
            if (details.reason === "item-press") return // выбор подсказки обрабатывает сам пункт
            s.input = value
            emit()
          }}
        >
          <FieldGroup>
            <Field orientation="horizontal" className="flex-wrap">
              <InputGroup ref={anchor} className="min-w-60 flex-1">
                <InputGroupAddon>
                  <SearchIcon />
                </InputGroupAddon>
                <Autocomplete.Input
                  render={<InputGroupInput />}
                  data-testid="checks-input"
                  aria-label={t("checks.input.label")}
                  placeholder={t("checks.input.placeholder")}
                  autoComplete="off"
                  spellCheck={false}
                  onKeyDown={(e) => {
                    // Enter по подсвеченной подсказке выбирает её, иначе проверяет набранное
                    if (e.key === "Enter" && !(shown && highlighted.current)) void checkTyped()
                  }}
                />
              </InputGroup>
              <Button data-testid="checks-run" disabled={!!run} onClick={() => void checkTyped()}>
                {run && <Spinner data-icon="inline-start" />}
                {t("checks.run")}
              </Button>
            </Field>
          </FieldGroup>
          <Autocomplete.Portal>
            <Autocomplete.Positioner anchor={anchor} sideOffset={4} className="isolate z-50">
              <Autocomplete.Popup
                data-testid="checks-suggestions"
                className="max-h-[min(var(--available-height),24rem)] w-(--anchor-width) overflow-y-auto rounded-md bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
              >
                <Autocomplete.List className="p-1">
                  {(group: SuggestionGroup) => (
                    <Autocomplete.Group key={group.value} items={group.items}>
                      <Autocomplete.GroupLabel className="px-2 py-1.5 text-xs text-muted-foreground">
                        {t(group.value === "lists" ? "checks.suggest.lists" : "checks.suggest.sites")}
                      </Autocomplete.GroupLabel>
                      <Autocomplete.Collection>
                        {(it: Suggestion) => (
                          <Autocomplete.Item
                            key={`${it.kind}:${suggestionText(it)}`}
                            value={it}
                            data-testid={`checks-suggest-${it.kind}-${suggestionText(it)}`}
                            onClick={() => pickSuggestion(it)}
                            className="flex w-full cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
                          >
                            <SuggestionBody it={it} q={q} />
                          </Autocomplete.Item>
                        )}
                      </Autocomplete.Collection>
                    </Autocomplete.Group>
                  )}
                </Autocomplete.List>
              </Autocomplete.Popup>
            </Autocomplete.Positioner>
          </Autocomplete.Portal>
        </Autocomplete.Root>
        {registryDown && (
          <Alert data-testid="checks-registry-down">
            <TriangleAlertIcon />
            <AlertDescription>{t("checks.registryDown")}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

export function ChecksPage() {
  const view = useView()
  useEffect(() => {
    void loadLists()
    void loadRegistryStatus()
  }, [])
  return (
    <Page id="checks" title={t("nav.checks")}>
      <CheckForm view={view} />
      {(view.results.size > 0 || view.run) && <Results view={view} />}
    </Page>
  )
}
