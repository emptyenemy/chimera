/* Диалог «Свой DNS-провайдер»: название, DoH-адрес и до двух IP сервера. */

import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { loadOverview } from "@/pages/hosts-data"

export function AddProviderDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("")
  const [doh, setDoh] = useState("")
  const [ip1, setIp1] = useState("")
  const [ip2, setIp2] = useState("")
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await api("hosts_add_provider", name.trim(), doh.trim(), [ip1.trim(), ip2.trim()])
      notify.success(t("hosts.add.done"))
      onClose()
      await loadOverview()
    } catch (e) {
      notify.error(t("hosts.add.failed"), e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="hosts-add-dialog">
        <form
          className="grid gap-6"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("hosts.add.title")}</DialogTitle>
            <DialogDescription>{t("hosts.add.desc")}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="hosts-add-name">{t("hosts.add.name")}</FieldLabel>
              <Input
                id="hosts-add-name"
                data-testid="hosts-add-name"
                autoFocus
                value={name}
                placeholder={t("hosts.add.namePlaceholder")}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="hosts-add-doh">{t("hosts.add.doh")}</FieldLabel>
              <Input
                id="hosts-add-doh"
                data-testid="hosts-add-doh"
                className="font-mono"
                value={doh}
                placeholder={t("hosts.add.dohPlaceholder")}
                onChange={(e) => setDoh(e.target.value)}
              />
            </Field>
            <FieldGroup className="grid grid-cols-2 gap-4">
              <Field>
                <FieldLabel htmlFor="hosts-add-ip1">{t("hosts.add.ip1")}</FieldLabel>
                <Input
                  id="hosts-add-ip1"
                  data-testid="hosts-add-ip1"
                  className="font-mono"
                  value={ip1}
                  placeholder={t("hosts.add.optional")}
                  onChange={(e) => setIp1(e.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="hosts-add-ip2">{t("hosts.add.ip2")}</FieldLabel>
                <Input
                  id="hosts-add-ip2"
                  data-testid="hosts-add-ip2"
                  className="font-mono"
                  value={ip2}
                  placeholder={t("hosts.add.optional")}
                  onChange={(e) => setIp2(e.target.value)}
                />
              </Field>
            </FieldGroup>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" data-testid="hosts-add-ok" disabled={busy}>
              {busy && <Spinner data-icon="inline-start" />}
              {t("hosts.add.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
