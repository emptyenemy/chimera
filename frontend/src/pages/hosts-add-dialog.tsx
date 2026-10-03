/* Диалог «Свой DNS-провайдер»: название, DoH-адрес и до двух IP сервера.
   С provider — правка своего, с copy — копия встроенного (сохраняется как новый). */

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
import { loadOverview, type Provider } from "@/pages/hosts-data"

export function AddProviderDialog({
  onClose,
  provider = null,
  copy = false,
}: {
  onClose: () => void
  provider?: Provider | null
  copy?: boolean
}) {
  const editing = !!provider && !copy
  const [name, setName] = useState(provider ? (copy ? `${provider.name} (${t("dns.copy.suffix")})` : provider.name) : "")
  const [doh, setDoh] = useState(provider?.doh ?? "")
  const [ip1, setIp1] = useState(provider?.servers?.[0] ?? "")
  const [ip2, setIp2] = useState(provider?.servers?.slice(1).join(", ") ?? "")
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      const servers = [ip1.trim(), ip2.trim()]
      if (editing && provider) await api("hosts_update_provider", provider.id, name.trim(), doh.trim(), servers)
      else await api("hosts_add_provider", name.trim(), doh.trim(), servers)
      notify.success(t(editing ? "hosts.edit.done" : "hosts.add.done"))
      onClose()
      await loadOverview()
    } catch (e) {
      notify.error(t(editing ? "hosts.edit.failed" : "hosts.add.failed"), e instanceof Error ? e.message : String(e))
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
            <DialogTitle>{t(editing ? "hosts.edit.title" : "hosts.add.title")}</DialogTitle>
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
              {t(editing ? "hosts.edit.save" : "hosts.add.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
