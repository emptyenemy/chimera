/* Состояние сайдбара в localStorage "chimera.sidebar" — тот же ключ и формат
   ({collapsed, width}), что у старого фронта: переключение между ними ничего не сбрасывает. */

const KEY = "chimera.sidebar"

export const SIDEBAR_WIDTH_DEFAULT = 232
export const SIDEBAR_WIDTH_MIN = 180
export const SIDEBAR_WIDTH_MAX = 360
/** Тянуть уже этого — значит свернуть в полосу иконок. */
export const SIDEBAR_SNAP = 120

export interface SidebarPrefs {
  collapsed?: boolean
  width?: number | null
}

export function loadSidebar(): SidebarPrefs {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}") || {}
  } catch {
    return {}
  }
}

export function saveSidebar(patch: SidebarPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...loadSidebar(), ...patch }))
  } catch {
    /* без localStorage настройки просто не запомнятся */
  }
}
