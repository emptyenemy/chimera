import type { TgState } from "@/lib/types"

/** Полное состояние Telegram-прокси (ключ хаба tg): поля, которые читает страница. */
export interface TgFull extends TgState {
  secret?: string
  autostart?: boolean
  link?: string
  disable_secure?: boolean
  fallback_cfproxy?: boolean
  cfproxy_user_domains?: string[]
  cfproxy_worker_domains?: string[]
  fake_tls_domain?: string
  dc_redirects?: Record<string, string>
  proxy_protocol?: boolean
  force_test_dc?: boolean
  apply_error?: string
}

/** Живая статистика ядра (ключ хаба tgStats, есть только у работающего прокси). */
export interface TgStats {
  active: number
  total: number
  ws: number
  tcp_fallback: number
  cfproxy: number
  up: string
  down: string
}
