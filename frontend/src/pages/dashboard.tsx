/* Обзор: общий статус защиты и быстрые тумблеры всех модулей. Эталон устройства
   страницы: рисуется только из стора, тумблеры — optimistic(), своих опросов нет. */

import { useState, type ReactNode } from "react"
import { PowerIcon, ShieldCheckIcon, ShieldOffIcon, WandSparklesIcon } from "lucide-react"
import { cn } from "cn"

import { Page } from "@/components/app/page"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { MODULE_TOTAL, useStatus } from "@/lib/status"
import { optimistic, store, useStore, useStoreError } from "@/lib/store"
import { useTrialPending } from "@/lib/trials"
import type { AppInfo } from "@/lib/types"
import { MODULES, proxyScope, type ModuleDef } from "@/pages/dashboard-modules"

const PENDING_KEY = "dash.pending"
type Pending = Record<string, boolean>

// Плитка с иконкой: серая, пока модуль выключен, и цвета акцента, когда включён.
function IconTile({ on, className, children }: { on: boolean; className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center rounded-lg transition-colors",
        on ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
        className
      )}
    >
      {children}
    </div>
  )
}

function Hero() {
  const { guard, count } = useStatus()
  return (
    <Card data-testid="dashboard-hero" data-state={guard ? "on" : "off"} className={cn(guard && "ring-primary/40")}>
      <CardContent className="flex-row items-center gap-4">
        <IconTile on={guard} className="size-12 [&_svg]:size-6">
          {guard ? <ShieldCheckIcon /> : <ShieldOffIcon />}
        </IconTile>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="text-lg leading-6 font-semibold tracking-tight">
            {guard ? t("dashboard.hero.on") : t("dashboard.hero.off")}
          </div>
          <div className="text-muted-foreground">
            {count ? t("dashboard.hero.count", { n: count, total: MODULE_TOTAL }) : t("dashboard.hero.hint")}
          </div>
        </div>
        {!guard && (
          // новичку не нужно знать, что такое стратегия: автонастройка подберёт сама
          <Button data-testid="dashboard-autotune" className="shrink-0" onClick={() => router.go("autotune")}>
            <WandSparklesIcon data-icon="inline-start" />
            {t("dashboard.hero.autotune")}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

async function toggleModule(m: ModuleDef<object>, target: boolean) {
  const st = store.get<object>(m.key)
  const app = store.get<AppInfo>("app")
  if (!st || m.blocked(st, app)) return
  const module = t(m.titleKey)
  store.set(PENDING_KEY, { ...store.get<Pending>(PENDING_KEY), [m.key]: true })
  try {
    await optimistic(m.key, m.patch ? m.patch(target) : { running: target }, () => m.toggle(st, target), {
      errorTitle: t(target ? "dashboard.toggleFailed.on" : "dashboard.toggleFailed.off", { module }),
    })
  } catch {
    /* тост уже показан, стор откатен */
  } finally {
    const rest = { ...store.get<Pending>(PENDING_KEY) }
    delete rest[m.key]
    store.set(PENDING_KEY, rest)
  }
}

// Одна строка под названием: ошибка, если есть; почему не включить; иначе — суть модуля.
function ModuleLine({ m, st, on, pending }: { m: ModuleDef<object>; st: object | undefined; on: boolean; pending: boolean }) {
  const hubError = useStoreError(m.key)
  const app = useStore<AppInfo>("app")
  const err = hubError || (st as { error?: string } | undefined)?.error
  const blocked = m.blocked(st, app)
  let text: string
  let tone = ""
  if (pending) {
    text = t(on ? "dashboard.pending.on" : "dashboard.pending.off")
  } else if (err) {
    text = String(err).slice(0, 120)
    tone = "text-destructive"
  } else if (blocked && !on) {
    text = blocked
    tone = "text-warning"
  } else {
    text = [m.meta(st), m.key === "proxy" && st ? proxyScope(st) : ""].filter(Boolean).join(" · ")
  }
  return (
    <div data-testid={`module-meta-${m.key}`} className={cn("truncate text-[13px] leading-[18px] text-muted-foreground", tone)}>
      {text || " "}
    </div>
  )
}

function ModuleCard({ m }: { m: ModuleDef<object> }) {
  const st = useStore<object>(m.key)
  const app = useStore<AppInfo>("app")
  const trialPending = useTrialPending()
  const pending = !!useStore<Pending>(PENDING_KEY)?.[m.key]
  const on = m.on(st)
  const blocked = !!m.blocked(st, app)
  const title = t(m.titleKey)
  const Icon = m.icon
  return (
    <Card
      size="sm"
      data-testid={`module-${m.key}`}
      data-state={on ? "on" : "off"}
      className={cn("relative transition-colors hover:bg-muted/40", on && "ring-primary/40")}
    >
      <CardContent className="flex-row items-center gap-3">
        <IconTile on={on} className="size-9 [&_svg]:size-[18px]">
          <Icon />
        </IconTile>
        <div className="flex min-w-0 grow flex-col">
          {/* вся карточка ведёт на страницу модуля: растянутая ссылка под переключателем */}
          <button
            type="button"
            data-testid={`module-open-${m.key}`}
            onClick={() => router.go(m.page)}
            className="w-fit rounded-sm text-left leading-5 font-semibold outline-none after:absolute after:inset-0 after:content-[''] focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {title}
          </button>
          <ModuleLine m={m} st={st} on={on} pending={pending} />
        </div>
        {pending && <Spinner className="relative text-muted-foreground" />}
        <Switch
          data-testid={`module-toggle-${m.key}`}
          className="relative"
          aria-label={t("dashboard.toggle", { module: title })}
          checked={on}
          disabled={blocked || pending || trialPending}
          onCheckedChange={(checked) => void toggleModule(m, checked)}
        />
      </CardContent>
    </Card>
  )
}

const STEP_KEYS: Record<string, string> = {
  service: "dashboard.panic.step.service",
  winws: "dashboard.panic.step.winws",
  proxy: "dashboard.panic.step.proxy",
  tg: "dashboard.panic.step.tg",
  hosts: "dashboard.panic.step.hosts",
  dns: "dashboard.panic.step.dns",
}

interface PanicReply {
  steps?: { step: string; ok: boolean; error?: string }[]
}

// «Выключить всё»: обход, прокси, Telegram, hosts, DNS, служба — разом; модули и
// настройки остаются, включить обратно можно переключателями ниже
async function panicAll(): Promise<void> {
  const ok = await confirmDialog({
    title: t("dashboard.panic.title"),
    description: t("dashboard.panic.desc"),
    confirmText: t("dashboard.panic.confirm"),
    destructive: true,
  })
  if (!ok) return
  try {
    const res = await api<PanicReply>("panic_all")
    const failed = (res?.steps ?? []).filter((s) => !s.ok)
    if (!failed.length) notify.success(t("dashboard.panic.done"))
    else
      notify.warning(
        t("dashboard.panic.partial"),
        failed.map((s) => `${STEP_KEYS[s.step] ? t(STEP_KEYS[s.step]) : s.step}: ${s.error}`).join("; ")
      )
  } catch (e) {
    notify.error(t("dashboard.panic.failed"), e instanceof Error ? e.message : String(e))
  }
}

function PanicButton() {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      variant="outline"
      size="sm"
      data-testid="dashboard-panic"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        try {
          await panicAll()
        } finally {
          setBusy(false)
        }
      }}
    >
      {busy ? <Spinner data-icon="inline-start" /> : <PowerIcon data-icon="inline-start" />}
      {t("dashboard.panic.button")}
    </Button>
  )
}

export function DashboardPage() {
  return (
    <Page id="dashboard" title={t("nav.dashboard")} actions={<PanicButton />}>
      <Hero />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {MODULES.map((m) => (
          <ModuleCard key={m.key} m={m} />
        ))}
      </div>
    </Page>
  )
}
