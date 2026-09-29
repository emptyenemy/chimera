/* Реестр страниц: порядок здесь — порядок в меню, группа — подпись над пунктами.
   Чтобы добавить страницу: компонент в pages/, строка сюда, строки в locales/ru.json
   (см. docs/FRONTEND.md). */

import type { ComponentType } from "react"
import {
  GlobeIcon,
  LayoutDashboardIcon,
  ListIcon,
  NetworkIcon,
  ScanSearchIcon,
  SendIcon,
  ServerIcon,
  SettingsIcon,
  ShieldIcon,
  type LucideIcon,
} from "lucide-react"

import type { ModuleKey } from "@/lib/types"
import { DashboardPage } from "@/pages/dashboard"
import { SettingsPage } from "@/pages/settings"
import { HostsPage } from "@/pages/hosts"
import { ListsPage } from "@/pages/lists"
import { ProxyPage } from "@/pages/proxy"
import { TelegramPage } from "@/pages/telegram"
import { ChecksPage } from "@/pages/checks"
import { DnsPage } from "@/pages/dns"
import { StrategiesPage } from "@/pages/strategies"

export interface PageDef {
  id: string
  /** Ключ строки с названием в каталоге. */
  titleKey: string
  icon: LucideIcon
  /** Ключ строки с названием группы; пустая — пункт без группы. */
  groupKey: string
  /** Точка состояния у пункта меню: от какого источника хаба она горит. */
  dot?: ModuleKey
  component: ComponentType
}

export const PAGES: PageDef[] = [
  { id: "dashboard", titleKey: "nav.dashboard", icon: LayoutDashboardIcon, groupKey: "", component: DashboardPage },
  { id: "strategies", titleKey: "nav.strategies", icon: ShieldIcon, groupKey: "nav.group.bypass", dot: "winws", component: StrategiesPage },
  { id: "proxy", titleKey: "nav.proxy", icon: GlobeIcon, groupKey: "nav.group.bypass", dot: "proxy", component: ProxyPage },
  { id: "telegram", titleKey: "nav.telegram", icon: SendIcon, groupKey: "nav.group.bypass", dot: "tg", component: TelegramPage },
  { id: "hosts", titleKey: "nav.hosts", icon: ServerIcon, groupKey: "nav.group.network", dot: "hosts", component: HostsPage },
  { id: "dns", titleKey: "nav.dns", icon: NetworkIcon, groupKey: "nav.group.network", component: DnsPage },
  { id: "lists", titleKey: "nav.lists", icon: ListIcon, groupKey: "nav.group.data", component: ListsPage },
  { id: "checks", titleKey: "nav.checks", icon: ScanSearchIcon, groupKey: "nav.group.data", component: ChecksPage },
  { id: "settings", titleKey: "nav.settings", icon: SettingsIcon, groupKey: "nav.group.system", component: SettingsPage },
]

export const PAGE_IDS = PAGES.map((p) => p.id)

export function pageById(id: string): PageDef {
  return PAGES.find((p) => p.id === id) ?? PAGES[0]
}
