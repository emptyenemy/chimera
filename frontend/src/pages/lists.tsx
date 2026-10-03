/* Списки доменов и IP (lists/*.txt) — общий источник для прокси, hosts и запрета DPI.
   Слева файлы с метками подключений и поиском, справа редактор с автосохранением.
   Список — до нескольких тысяч строк, поэтому текст живёт в неуправляемой textarea:
   React не перерисовывает его на каждое нажатие (аналог data-morph="skip" прежнего
   фронта), а тяжёлое (запрос на сохранение) висит на debounce. */

import { useCallback, useDeferredValue, useEffect, useRef, useState, type ChangeEvent } from "react"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  EllipsisIcon,
  FileTextIcon,
  GlobeIcon,
  ListIcon,
  PencilIcon,
  PlusIcon,
  RadarIcon,
  SearchIcon,
  ServerIcon,
  ShieldIcon,
  Trash2Icon,
  type LucideIcon,
} from "lucide-react"

import { Page } from "@/components/app/page"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/bridge"
import { confirmDialog, promptDialog } from "@/lib/dialogs"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store, useStore } from "@/lib/store"
import { RecordDialog } from "@/pages/lists-record-dialog"
import { LISTS_KEY, applyErrors, applySelections, patchList, readListDraft, registerEditor, setTransport, settleListDraft, track, waitSaved, withSavedList, writeListDraft, type ListInfo, type SaveInfo } from "@/pages/lists-data"

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

type Transport = "proxy" | "winws" | "hosts"

const TRANSPORT_ICONS: Record<Transport, LucideIcon> = {
  proxy: GlobeIcon,
  winws: ShieldIcon,
  hosts: ServerIcon,
}
const TRANSPORTS: Transport[] = ["proxy", "winws", "hosts"]

const transportName = (k: Transport) =>
  k === "proxy" ? t("lists.transport.proxy") : k === "winws" ? t("lists.transport.winws") : t("lists.transport.hosts")

let listGeneration = 0
async function loadLists(): Promise<void> {
  const generation = ++listGeneration
  const before = { proxy: store.get("proxy"), winws: store.get("winws") }
  try {
    const items = await api<ListInfo[]>("lists_all")
    if (generation === listGeneration) store.set(LISTS_KEY, applySelections(items, before))
  } catch (e) {
    if (generation !== listGeneration) return
    if (!store.get(LISTS_KEY)) store.set(LISTS_KEY, [])
    notify.error(t("lists.load.failed"), msg(e))
  }
}

async function createList(): Promise<string | null> {
  const name = await promptDialog({
    title: t("lists.create.title"),
    label: t("lists.create.label"),
    placeholder: t("lists.create.placeholder"),
    confirmText: t("lists.create.confirm"),
  })
  const trimmed = name?.trim()
  if (!trimmed) return null
  try {
    await api("lists_create", trimmed)
    await loadLists()
    return trimmed
  } catch (e) {
    notify.error(t("lists.create.failed"), msg(e))
    return null
  }
}

/** Возвращает новое имя, если список переименован. */
async function renameList(name: string): Promise<string | null> {
  const next = (
    await promptDialog({ title: t("lists.rename.title"), label: t("lists.rename.label"), value: name })
  )?.trim()
  if (!next || next === name) return null
  if (!/^[A-Za-z0-9._-]+$/.test(next)) {
    notify.error(t("lists.rename.badName"), t("lists.rename.badNameDesc"))
    return null
  }
  if (store.get<ListInfo[]>(LISTS_KEY)?.some((f) => f.name === next)) {
    notify.error(t("lists.rename.failed"), t("lists.rename.exists", { name: next }))
    return null
  }
  try {
    const info = await withSavedList(name, () => api<{ name?: string } | null>("lists_rename", name, next), true)
    const renamed = info?.name ?? next
    notify.success(`${name} → ${renamed}`)
    await loadLists()
    return renamed
  } catch (e) {
    notify.error(t("lists.rename.failed"), msg(e))
    return null
  }
}

async function deleteList(name: string): Promise<boolean> {
  const ok = await confirmDialog({
    title: t("lists.delete.title"),
    description: t("lists.delete.desc", { name }),
    confirmText: t("lists.delete.confirm"),
    destructive: true,
  })
  if (!ok) return false
  try {
    const res = await withSavedList(name, () => api<SaveInfo | null>("lists_delete", name), true)
    notify.success(t("lists.delete.done", { name }))
    applyErrors(res, "lists.delete.applyFailed")
    await loadLists()
    return true
  } catch (e) {
    notify.error(t("lists.delete.failed"), msg(e))
    return false
  }
}

// --- редактор -----------------------------------------------------------------

type SaveState = "" | "saving" | "saved" | "error"

function SaveBadge({ status }: { status: SaveState }) {
  if (status === "saving")
    return (
      <Badge variant="outline" data-testid="lists-status" data-state="saving">
        <Spinner data-icon="inline-start" />
        {t("lists.status.saving")}
      </Badge>
    )
  if (status === "saved")
    return (
      <Badge variant="secondary" data-testid="lists-status" data-state="saved">
        <CircleCheckIcon data-icon="inline-start" />
        {t("lists.status.saved")}
      </Badge>
    )
  if (status === "error")
    return (
      <Badge variant="destructive" data-testid="lists-status" data-state="error">
        <CircleAlertIcon data-icon="inline-start" />
        {t("lists.status.error")}
      </Badge>
    )
  return null
}

function TransportField({ item }: { item: ListInfo }) {
  const active = TRANSPORTS.filter((k) => item[k])
  return (
    <Field orientation="responsive">
      <FieldContent>
        <FieldTitle id="lists-transport-title">{t("lists.transport.title")}</FieldTitle>
        <FieldDescription>{t("lists.transport.desc")}</FieldDescription>
      </FieldContent>
      <ToggleGroup
        multiple
        variant="outline"
        size="sm"
        spacing={1}
        aria-labelledby="lists-transport-title"
        data-testid="lists-transport"
        value={active}
        onValueChange={(next) => {
          for (const k of ["proxy", "winws"] as const) {
            if (next.includes(k) !== !!item[k]) void setTransport(item.name, k, next.includes(k))
          }
        }}
      >
        {TRANSPORTS.map((k) => {
          const Icon = TRANSPORT_ICONS[k]
          return (
            <ToggleGroupItem
              key={k}
              value={k}
              disabled={k === "hosts"}
              data-testid={`lists-transport-${k}`}
              title={k === "hosts" ? t("lists.transport.hostsHint") : undefined}
            >
              <Icon data-icon="inline-start" />
              {transportName(k)}
            </ToggleGroupItem>
          )
        })}
      </ToggleGroup>
    </Field>
  )
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" }

// строка списка: запись обычным цветом, всё после # — тусклым комментарием
function highlightList(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const safe = line.replace(/[&<>]/g, (c) => ESCAPES[c])
      const at = safe.indexOf("#")
      return at < 0 ? safe : `${safe.slice(0, at)}<span class="text-muted-foreground/70">${safe.slice(at)}</span>`
    })
    .join("\n")
}

function ListEditor({ name, item }: { name: string; item?: ListInfo }) {
  const [text, setText] = useState<string | null>(null) // null — читается
  const [loadError, setLoadError] = useState("")
  const [status, setStatus] = useState<SaveState>("")
  const [saveError, setSaveError] = useState("")
  const [frozen, setFrozen] = useState(false)
  const [count, setCount] = useState<number | null>(item?.count ?? null)

  const latest = useRef("")
  const dirty = useRef(false)
  const timer = useRef(0)
  const alive = useRef(true)
  const saveSequence = useRef(0)
  const retired = useRef(false)
  const lastSave = useRef<Promise<boolean>>(Promise.resolve(true))
  const area = useRef<HTMLTextAreaElement>(null)
  const layer = useRef<HTMLPreElement>(null)
  const paintFrame = useRef(0)

  // textarea неуправляемая, поэтому слой подсветки рисуем напрямую — без перерисовки React
  const paint = useCallback(() => {
    cancelAnimationFrame(paintFrame.current)
    paintFrame.current = requestAnimationFrame(() => {
      if (!area.current || !layer.current) return
      // перевод строки в конце: иначе пустая последняя строка не займёт высоту
      layer.current.innerHTML = highlightList(area.current.value) + "\n"
      layer.current.scrollTop = area.current.scrollTop
    })
  }, [])
  useEffect(() => {
    if (text !== null) paint()
    return () => cancelAnimationFrame(paintFrame.current)
  }, [text, paint])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      // недосохранённая правка этого же списка ещё в пути — сначала дождёмся её
      await waitSaved(name)
      if (cancelled) return
      const draft = readListDraft(name)
      if (draft) {
        latest.current = draft.text
        dirty.current = true
        setText(draft.text)
        setSaveError(draft.error ?? "")
        setStatus(draft.error !== null ? "error" : "saving")
        return
      }
      try {
        const v = await api<string>("lists_read", name)
        if (cancelled) return
        latest.current = v ?? ""
        setText(latest.current)
      } catch (e) {
        if (cancelled) return
        setLoadError(msg(e))
        setText("")
        notify.error(t("lists.open.failed"), msg(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [name])

  const flush = useCallback((): Promise<boolean> => {
    window.clearTimeout(timer.current)
    if (!dirty.current) return lastSave.current
    dirty.current = false
    const sequence = ++saveSequence.current
    const value = latest.current
    const draft = readListDraft(name)
    const saving = (async () => {
      try {
        const info = await track(name, () => api<SaveInfo | null>("lists_save", name, value))
        if (info) patchList(name, { count: info.count })
        applyErrors(info, "lists.saveApplyFailed")
        settleListDraft(name, draft, null)
        if (alive.current && sequence === saveSequence.current) {
          if (info) setCount(info.count)
          setSaveError("")
          setStatus(dirty.current ? "saving" : "saved")
        }
        return true
      } catch (e) {
        const retained = settleListDraft(name, draft, msg(e))
        if (retained && !alive.current) notify.error(t("lists.saveFailed", { name }), `${msg(e)}\n${t("lists.draftRetained")}`)
        if (sequence === saveSequence.current) {
          dirty.current = true
          if (alive.current) {
            setSaveError(msg(e))
            setStatus("error")
          }
        }
        return false
      }
    })()
    lastSave.current = saving
    return saving
  }, [name])

  // уходим со списка или со страницы — недосохранённое уходит на диск сразу
  useEffect(() => {
    alive.current = true
    const unregister = registerEditor(name, {
      flush,
      freeze: (on) => { if (alive.current) setFrozen(on || retired.current) },
      retire: () => {
        retired.current = true
        dirty.current = false
        window.clearTimeout(timer.current)
      },
    })
    return () => {
      unregister()
      alive.current = false
      void flush()
    }
  }, [name, flush])

  const onChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    paint()
    latest.current = e.target.value
    writeListDraft(name, latest.current)
    dirty.current = true
    setSaveError("")
    setStatus("saving")
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void flush(), 500)
  }

  return (
    <Card data-testid="lists-editor" data-list={name} className="min-w-0">
      <CardHeader>
        <CardTitle className="font-mono">{name}.txt</CardTitle>
        <CardAction className="flex items-center gap-3">
          <SaveBadge status={status} />
          {count != null && (
            <span className="font-mono text-muted-foreground" data-testid="lists-count">
              {t("lists.records", { count, n: fmtNum(count) })}
            </span>
          )}
        </CardAction>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          {item && <TransportField item={item} />}
          <Field>
            <FieldLabel htmlFor="lists-textarea" className="sr-only">
              {t("lists.editor.label", { name })}
            </FieldLabel>
            {text === null ? (
              <div className="flex flex-col gap-2" data-testid="lists-editor-loading">
                {Array.from({ length: 10 }, (_, i) => (
                  <Skeleton key={i} className="h-4 w-full" />
                ))}
              </div>
            ) : loadError ? null : (
              <div className="relative rounded-md dark:bg-input/30">
                {/* тот же шрифт, отступы и рамка, что у textarea: строки совпадают пиксель в пиксель */}
                <pre
                  ref={layer}
                  aria-hidden
                  className="pointer-events-none absolute inset-0 m-0 overflow-hidden rounded-md border border-transparent px-2.5 py-2 font-mono text-base break-words whitespace-pre-wrap [scrollbar-gutter:stable] md:text-sm"
                />
                <Textarea
                  ref={area}
                  id="lists-textarea"
                  data-testid="lists-textarea"
                  className="relative field-sizing-fixed h-[420px] resize-none bg-transparent font-mono text-transparent caret-foreground [scrollbar-gutter:stable] selection:bg-primary/30 dark:bg-transparent"
                  spellCheck={false}
                  placeholder={t("lists.editor.placeholder")}
                  readOnly={frozen}
                  aria-busy={frozen}
                  defaultValue={text}
                  onChange={onChange}
                  onScroll={(e) => {
                    if (layer.current) layer.current.scrollTop = e.currentTarget.scrollTop
                  }}
                  onBlur={() => void flush()}
                />
              </div>
            )}
          </Field>
        </FieldGroup>
      </CardContent>
      {(loadError || saveError) && (
        <CardContent>
          <Alert variant="destructive" data-testid="lists-error">
            <CircleAlertIcon />
            <AlertDescription>{loadError || saveError}</AlertDescription>
          </Alert>
        </CardContent>
      )}
    </Card>
  )
}

// --- левая колонка --------------------------------------------------------------

interface RowMenuProps {
  item: ListInfo
  onRenamed: (from: string, to: string) => void
  onDeleted: (name: string) => void
}

function RowMenu(props: RowMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon-xs" data-testid={`list-menu-${props.item.name}`} />}
        aria-label={t("lists.menu.label", { name: props.item.name })}
      >
        <EllipsisIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <RowMenuItems {...props} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// пункты общие для «⋯» и правого клика: контекстное меню Base UI собрано из тех же частей Menu
function RowMenuItems({ item, onRenamed, onDeleted }: RowMenuProps) {
  return (
    <>
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("lists.transport.title")}</DropdownMenuLabel>
          <DropdownMenuCheckboxItem
            checked={!!item.proxy}
            data-testid="list-menu-proxy"
            onCheckedChange={(v) => void setTransport(item.name, "proxy", v)}
          >
            <GlobeIcon />
            {t("lists.transport.proxyMenu")}
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={!!item.winws}
            data-testid="list-menu-winws"
            onCheckedChange={(v) => void setTransport(item.name, "winws", v)}
          >
            <ShieldIcon />
            {t("lists.transport.winwsMenu")}
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem checked={!!item.hosts} disabled title={t("lists.transport.hostsHint")}>
            <ServerIcon />
            {t("lists.transport.hostsMenu")}
          </DropdownMenuCheckboxItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            data-testid="list-rename"
            onClick={() =>
              void renameList(item.name).then((to) => {
                if (to) onRenamed(item.name, to)
              })
            }
          >
            <PencilIcon />
            {t("lists.menu.rename")}
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            data-testid="list-delete"
            onClick={() =>
              void deleteList(item.name).then((ok) => {
                if (ok) onDeleted(item.name)
              })
            }
          >
            <Trash2Icon />
            {t("lists.menu.delete")}
          </DropdownMenuItem>
        </DropdownMenuGroup>
    </>
  )
}

function ListsSide({
  lists,
  current,
  onOpen,
  onCreated,
  onRenamed,
  onDeleted,
}: {
  lists: ListInfo[] | undefined
  current: string | null
  onOpen: (name: string) => void
  onCreated: (name: string) => void
  onRenamed: (from: string, to: string) => void
  onDeleted: (name: string) => void
}) {
  const [query, setQuery] = useState("")
  const q = useDeferredValue(query).trim().toLowerCase()
  const items = lists && q ? lists.filter((f) => f.name.toLowerCase().includes(q)) : lists

  let body
  if (!items) {
    body = (
      <div className="flex flex-col gap-2" data-testid="lists-loading">
        {Array.from({ length: 7 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  } else if (!lists?.length) {
    body = (
      <Empty className="p-6" data-testid="lists-empty">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ListIcon />
          </EmptyMedia>
          <EmptyTitle>{t("lists.empty.title")}</EmptyTitle>
          <EmptyDescription>{t("lists.empty.desc")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  } else if (!items.length) {
    body = (
      <Empty className="p-6" data-testid="lists-nomatch">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SearchIcon />
          </EmptyMedia>
          <EmptyTitle>{t("lists.noMatch.title")}</EmptyTitle>
          <EmptyDescription>{t("lists.noMatch.desc", { query: query.trim() })}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  } else {
    body = (
      <div className="max-h-[420px] overflow-y-auto">
        <Table data-testid="lists-table">
          <TableBody>
            {items.map((f) => (
              <ContextMenu key={f.name}>
              <ContextMenuTrigger
                render={<TableRow />}
                data-testid={`list-row-${f.name}`}
                data-state={f.name === current ? "selected" : undefined}
                className="cursor-pointer"
                onClick={() => onOpen(f.name)}
              >
                <TableCell className="w-full max-w-0">
                  <button
                    type="button"
                    className="w-full truncate rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                    aria-current={f.name === current ? "true" : undefined}
                  >
                    {f.name}
                  </button>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1 text-muted-foreground">
                    {TRANSPORTS.filter((k) => f[k]).map((k) => {
                      const Icon = TRANSPORT_ICONS[k]
                      return (
                        <span
                          key={k}
                          data-testid={`list-badge-${k}`}
                          title={t("lists.transport.tip", { transport: transportName(k).toLowerCase() })}
                          className="[&_svg]:size-3.5"
                        >
                          <Icon />
                        </span>
                      )
                    })}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{fmtNum(f.count)}</Badge>
                </TableCell>
                {/* события меню всплывают через портал к строке — здесь их гасим */}
                <TableCell className="pl-0" onClick={(e) => e.stopPropagation()}>
                  <RowMenu item={f} onRenamed={onRenamed} onDeleted={onDeleted} />
                </TableCell>
              </ContextMenuTrigger>
              {/* клики по пунктам всплывают через портал к строке — гасим, чтобы не открывать список */}
              <ContextMenuContent className="min-w-52" onClick={(e) => e.stopPropagation()}>
                <RowMenuItems item={f} onRenamed={onRenamed} onDeleted={onDeleted} />
              </ContextMenuContent>
              </ContextMenu>
            ))}
          </TableBody>
        </Table>
      </div>
    )
  }

  return (
    <Card className="min-w-0" data-testid="lists-side">
      <CardHeader>
        <CardTitle>{t("lists.side.title")}</CardTitle>
        <CardAction>
          <Button
            variant="outline"
            size="icon-sm"
            data-testid="lists-new"
            aria-label={t("lists.new")}
            title={t("lists.new")}
            onClick={() =>
              void createList().then((name) => {
                if (name) onCreated(name)
              })
            }
          >
            <PlusIcon />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <InputGroup>
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            data-testid="lists-search"
            aria-label={t("lists.search.label")}
            placeholder={t("lists.search.placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </InputGroup>
        {body}
      </CardContent>
    </Card>
  )
}

export function ListsPage() {
  const lists = useStore<ListInfo[]>(LISTS_KEY)
  const [current, setCurrent] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [recording, setRecording] = useState(false)

  useEffect(() => {
    void loadLists()
  }, [])

  const item = lists?.find((f) => f.name === current)

  return (
    <Page
      id="lists"
      title={t("nav.lists")}
      actions={
        <Button variant="outline" size="sm" data-testid="lists-record" onClick={() => setRecording(true)}>
          <RadarIcon data-icon="inline-start" />
          {t("lists.record.button")}
        </Button>
      }
    >
      <div className="@container">
        <div className="grid grid-cols-1 items-start gap-4 @2xl:grid-cols-[300px_1fr]">
          <ListsSide
            lists={lists}
            current={current}
            onOpen={setCurrent}
            onCreated={setCurrent}
            onRenamed={(from, to) => setCurrent((c) => (c === from ? to : c))}
            onDeleted={(name) => setCurrent((c) => (c === name ? null : c))}
          />
          {current ? (
            <ListEditor key={`${current}:${reload}`} name={current} item={item} />
          ) : (
            <Card data-testid="lists-editor-empty">
              <CardContent>
                <Empty>
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <FileTextIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t("lists.none.title")}</EmptyTitle>
                    <EmptyDescription>{t("lists.none.desc")}</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
      {recording && (
        <RecordDialog
          lists={lists ?? []}
          onClose={() => setRecording(false)}
          onAdded={(name) => {
            // если дополнен открытый список — редактор перечитывает файл
            if (name === current) setReload((n) => n + 1)
          }}
        />
      )}
    </Page>
  )
}
