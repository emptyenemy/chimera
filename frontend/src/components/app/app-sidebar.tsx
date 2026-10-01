import { PanelLeftCloseIcon, PanelLeftOpenIcon, ServerIcon, ShieldIcon } from "lucide-react"

import { BrandLogo } from "@/components/app/brand-logo"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { fmtVersion } from "@/lib/format"
import { useState } from "react"
import { notify } from "@/lib/notify"
import { t } from "@/lib/i18n"
import { router, useCurrentPage } from "@/lib/router"
import { MODULE_TOTAL, useStatus } from "@/lib/status"
import { useStore, useStoreError } from "@/lib/store"
import type { AppInfo, ModuleKey, SelfUpdateState } from "@/lib/types"
import { PAGES, type PageDef } from "@/pages/registry"

/** Точка у пункта меню: горит, когда модуль страницы включён, красная — при ошибке опроса. */
function ElevateButton() {
  const [pending, setPending] = useState(false)
  return <Button variant="ghost" size="sm" data-testid="sidebar-elevate"
    title={t("startup.elevate")} disabled={pending}
    className="h-auto justify-start px-1.5 py-1 text-xs text-amber-500 group-data-[collapsible=icon]:px-0"
    onClick={() => {
      setPending(true)
      void api("app_elevate").catch((error: Error) => notify.error(error.message)).finally(() => setPending(false))
    }}>
    <ShieldIcon className="size-3.5 shrink-0" />
    <span className="group-data-[collapsible=icon]:hidden">{t("startup.elevate")}</span>
  </Button>
}

function NavDot({ module }: { module: ModuleKey }) {
  const status = useStatus()
  const error = useStoreError(module)
  if (!error && !status[module]) return null
  return (
    <span
      data-testid={`nav-dot-${module}`}
      className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 group-data-[collapsible=icon]:top-1.5 group-data-[collapsible=icon]:right-auto group-data-[collapsible=icon]:left-5 group-data-[collapsible=icon]:translate-y-0"
    >
      <StatusDot tone={error ? "err" : "on"} className="group-data-[collapsible=icon]:size-1.5 group-data-[collapsible=icon]:ring-2 group-data-[collapsible=icon]:ring-sidebar" />
    </span>
  )
}

function NavItem({ page, active }: { page: PageDef; active: boolean }) {
  const title = t(page.titleKey)
  const Icon = page.icon
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={title}
        isActive={active}
        aria-current={active ? "page" : undefined}
        data-testid={`nav-${page.id}`}
        onClick={() => router.go(page.id)}
      >
        <Icon />
        <span>{title}</span>
      </SidebarMenuButton>
      {page.dot && <NavDot module={page.dot} />}
    </SidebarMenuItem>
  )
}

function Header() {
  const { state, toggleSidebar } = useSidebar()
  const app = useStore<AppInfo>("app")
  const upd = useStore<SelfUpdateState>("selfupdate")
  const collapsed = state === "collapsed"
  const hasUpdate = !!upd?.update
  const updateTip = hasUpdate ? t("sidebar.update", { version: fmtVersion(upd?.latest) }) : ""

  if (collapsed) {
    // в полосе знак сам работает кнопкой «развернуть»: по наведению превращается в иконку
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              data-testid="sidebar-toggle"
              aria-label={t("sidebar.expand")}
              onClick={toggleSidebar}
              className="group/logo relative size-8 rounded-md outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring"
            />
          }
        >
          <BrandLogo className="transition-opacity group-hover/logo:opacity-0 group-focus-visible/logo:opacity-0" />
          <PanelLeftOpenIcon className="absolute inset-0 m-auto size-4 opacity-0 transition-opacity group-hover/logo:opacity-100 group-focus-visible/logo:opacity-100" />
        </TooltipTrigger>
        <TooltipContent side="right">{t("sidebar.expandHint")}</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <div className="flex items-center gap-2.5">
      <div className="size-8 shrink-0">
        <BrandLogo />
      </div>
      <div className="flex min-w-0 flex-col">
        <b className="text-sm leading-[18px] font-semibold tracking-wide">Chimera</b>
        <button
          type="button"
          data-testid="sidebar-version"
          disabled={!hasUpdate}
          title={updateTip}
          onClick={() => router.go("settings")}
          className="flex items-center gap-1 truncate text-left text-xs leading-4 text-muted-foreground enabled:cursor-pointer enabled:hover:text-foreground"
        >
          {fmtVersion(app?.version)}
          {hasUpdate && <StatusDot tone="warn" className="size-1.5" />}
        </button>
      </div>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto text-muted-foreground"
              data-testid="sidebar-toggle"
              aria-label={t("sidebar.collapse")}
              onClick={toggleSidebar}
            />
          }
        >
          <PanelLeftCloseIcon />
        </TooltipTrigger>
        <TooltipContent side="bottom">{t("sidebar.collapseHint")}</TooltipContent>
      </Tooltip>
    </div>
  )
}

function StatusRow({ tone, text, testId }: { tone: "off" | "on" | "warn"; text: string; testId: string }) {
  return (
    <div data-testid={testId} title={text} className="flex items-center gap-2 overflow-hidden px-2 py-1.5 text-xs leading-4 text-muted-foreground">
      <StatusDot tone={tone} />
      <span className="truncate group-data-[collapsible=icon]:hidden">{text}</span>
    </div>
  )
}

export function AppSidebar() {
  const current = useCurrentPage()
  const status = useStatus()
  const app = useStore<AppInfo>("app")

  const state = status.guard
    ? t("status.guardOn", { n: status.count, total: MODULE_TOTAL })
    : status.count
      ? t("status.some", { n: status.count, total: MODULE_TOTAL })
      : t("status.none")

  // страницы по группам, в порядке реестра
  const groups: { key: string; pages: PageDef[] }[] = []
  for (const p of PAGES) {
    let g = groups.find((x) => x.key === p.groupKey)
    if (!g) groups.push((g = { key: p.groupKey, pages: [] }))
    g.pages.push(p)
  }

  return (
    <Sidebar collapsible="icon" data-testid="sidebar">
      <SidebarHeader className="px-2 pt-4 pb-2">
        <Header />
      </SidebarHeader>
      {app?.service_running && (
        <div className="px-2 pb-2">
          <Alert
            data-testid="sidebar-service"
            title={t("status.service")}
            className="border-0 bg-sidebar-accent px-2.5 py-2 text-xs group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:place-items-center group-data-[collapsible=icon]:px-0"
          >
            <ServerIcon />
            <AlertDescription className="group-data-[collapsible=icon]:hidden">{t("status.service")}</AlertDescription>
          </Alert>
        </div>
      )}
      <SidebarContent>
        {groups.map((g) => (
          <SidebarGroup key={g.key || "root"} className="py-1">
            {g.key && <SidebarGroupLabel>{t(g.key)}</SidebarGroupLabel>}
            <SidebarGroupContent>
              <SidebarMenu>
                {g.pages.map((p) => (
                  <NavItem key={p.id} page={p} active={current === p.id} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border">
        <div data-testid="sidebar-status" className="flex flex-col gap-0.5">
          <StatusRow testId="sidebar-status-guard" tone={status.guard ? "on" : "off"} text={state} />
          {app?.admin === false && <ElevateButton />}
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
