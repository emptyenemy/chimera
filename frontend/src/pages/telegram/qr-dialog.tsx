import { useMemo, useState } from "react"
import qrcode from "qrcode-generator"
import { TriangleAlertIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { optimistic, useStore } from "@/lib/store"
import type { TgFull } from "@/pages/telegram/types"

const isLoopback = (h: unknown) => ["", "127.0.0.1", "localhost", "::1"].includes(String(h ?? "").trim().toLowerCase())

// Чёрные модули на белом фоне в любой теме: на тёмном фоне камера код не считает,
// поэтому цвета здесь заданы прямо в SVG, а не токенами темы.
function QrCode({ text }: { text: string }) {
  const { size, path } = useMemo(() => {
    const qr = qrcode(0, "M")
    qr.addData(text)
    qr.make()
    const n = qr.getModuleCount()
    const quiet = 4
    let d = ""
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + quiet} ${r + quiet}h1v1h-1z`
    return { size: n + quiet * 2, path: d }
  }, [text])
  return (
    <svg
      data-testid="tg-qr-svg"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={t("tg.qr.label")}
      shapeRendering="crispEdges"
      className="block w-[280px] max-w-full overflow-hidden rounded-xl"
    >
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  )
}

/** QR для телефона. Телефон подключается по адресу компьютера в сети, а по умолчанию
    прокси слушает только 127.0.0.1 — тогда вместо кода предлагаем открыть его для сети. */
export function TgQrDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const st = useStore<TgFull>("tg")
  const [busy, setBusy] = useState(false)

  // без оптимистичной правки: ссылку с адресом компьютера в сети считает бэкенд,
  // а до его ответа QR показывал бы старую (127.0.0.1)
  const setHost = async (host: string) => {
    if (!st) return
    setBusy(true)
    try {
      await optimistic("tg", null, () => api("tg_set_config", host, Number(st.port), st.secret, !!st.autostart), {
        errorTitle: t("tg.qr.hostFailed"),
      })
    } catch {
      /* тост уже показан */
    } finally {
      setBusy(false)
    }
  }

  const local = isLoopback(st?.host)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="tg-qr-dialog">
        <DialogHeader>
          <DialogTitle>{t("tg.qr.title")}</DialogTitle>
          <DialogDescription>{t("tg.qr.desc")}</DialogDescription>
        </DialogHeader>
        {!st?.link ? (
          <p className="text-muted-foreground">{t("tg.qr.noLink")}</p>
        ) : local ? (
          <div className="flex flex-col gap-3" data-testid="tg-qr-local">
            <p>{t("tg.qr.localOnly", { host: st.host ?? "" })}</p>
            <p className="text-muted-foreground">{t("tg.qr.localHint")}</p>
            <Button data-testid="tg-qr-lan-open" disabled={busy} onClick={() => void setHost("0.0.0.0")}>
              {busy && <Spinner data-icon="inline-start" />}
              {t("tg.qr.lanOpen")}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-center">
            <QrCode text={st.link} />
            <p className="text-muted-foreground">{t("tg.qr.scan")}</p>
            {!st.running && (
              <Alert className="text-warning">
                <TriangleAlertIcon />
                <AlertDescription>{t("tg.qr.stopped")}</AlertDescription>
              </Alert>
            )}
            <Button variant="ghost" size="sm" data-testid="tg-qr-lan-close" disabled={busy} onClick={() => void setHost("127.0.0.1")}>
              {busy && <Spinner data-icon="inline-start" />}
              {t("tg.qr.lanClose")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
