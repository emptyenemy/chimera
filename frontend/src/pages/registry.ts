/* Реестр страниц: порядок здесь — порядок в меню, группа — подпись над пунктами.
   Чтобы добавить страницу: компонент в pages/, строка сюда, строки в locales/ru.json
   (см. docs/FRONTEND.md). */

import { createElement, type ComponentType } from "react"
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
import { StubPage } from "@/pages/stub"
import { ChecksPage } from "@/pages/checks"
import { DnsPage } from "@/pages/dns"

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

// пока страница не перенесена, вместо неё карточка «Скоро в новом интерфейсе»
const stub = (id: string): ComponentType => () => createElement(StubPage, { id, titleKey: `nav.${id}` })

export const PAGES: PageDef[] = [
  { id: "dashboard", titleKey: "nav.dashboard", icon: LayoutDashboardIcon, groupKey: "", component: DashboardPage },
  { id: "strategies", titleKey: "nav.strategies", icon: ShieldIcon, groupKey: "nav.group.bypass", dot: "winws", component: stub("strategies") },
  { id: "proxy", titleKey: "nav.proxy", icon: GlobeIcon, groupKey: "nav.group.bypass", dot: "proxy", component: stub("proxy") },
  { id: "telegram", titleKey: "nav.telegram", icon: SendIcon, groupKey: "nav.group.bypass", dot: "tg", component: stub("telegram") },
  { id: "hosts", titleKey: "nav.hosts", icon: ServerIcon, groupKey: "nav.group.network", dot: "hosts", component: stub("hosts") },
  { id: "dns", titleKey: "nav.dns", icon: NetworkIcon, groupKey: "nav.group.network", component: DnsPage },
  { id: "lists", titleKey: "nav.lists", icon: ListIcon, groupKey: "nav.group.data", component: stub("lists") },
  { id: "checks", titleKey: "nav.checks", icon: ScanSearchIcon, groupKey: "nav.group.data", component: ChecksPage },
  { id: "settings", titleKey: "nav.settings", icon: SettingsIcon, groupKey: "nav.group.system", component: stub("settings") },
]

export const PAGE_IDS = PAGES.map((p) => p.id)

export function pageById(id: string): PageDef {
  return PAGES.find((p) => p.id === id) ?? PAGES[0]
}
