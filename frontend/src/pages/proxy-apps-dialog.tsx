/* Выбор приложений для выборочного TUN: отметки только среди запущенных программ. */

import { useState } from "react"
import { SearchIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"

export interface RunningApp {
  name: string
  count: number
}

export function AppsPickerDialog({
  running,
  selected,
  onSave,
  onClose,
}: {
  running: RunningApp[]
  selected: string[]
  onSave: (names: string[]) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState("")
  const [chosen, setChosen] = useState(() => new Set(selected.map((a) => a.toLowerCase())))

  const q = query.trim().toLowerCase()
  const items = running.filter((r) => !q || r.name.toLowerCase().includes(q))

  const save = () => {
    // выбранные раньше и сейчас не запущенные — как были; среди запущенных — по отметкам
    const runningKeys = new Set(running.map((r) => r.name.toLowerCase()))
    const keep = selected.filter((a) => !runningKeys.has(a.toLowerCase()))
    const picked = running.filter((r) => chosen.has(r.name.toLowerCase())).map((r) => r.name)
    onSave([...keep, ...picked])
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="proxy-apps-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("proxy.apps.dialog.title")}</DialogTitle>
          <DialogDescription>{t("proxy.apps.dialog.desc")}</DialogDescription>
        </DialogHeader>
        <FieldGroup className="gap-3">
          <InputGroup>
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
            <InputGroupInput
              data-testid="proxy-apps-search"
              aria-label={t("proxy.apps.dialog.search")}
              placeholder={t("proxy.apps.dialog.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </InputGroup>
          {items.length === 0 ? (
            <Empty className="p-6">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SearchIcon />
                </EmptyMedia>
                <EmptyTitle>{t("proxy.apps.dialog.noMatch")}</EmptyTitle>
                <EmptyDescription>
                  {q ? t("proxy.apps.dialog.noMatchDesc", { query: query.trim() }) : t("proxy.apps.dialog.noRunning")}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <FieldGroup className="max-h-80 gap-1 overflow-y-auto" data-slot="checkbox-group">
              {items.map((r, i) => (
                <Field key={r.name} orientation="horizontal" className="rounded-md px-1 py-1.5 hover:bg-accent">
                  <Checkbox
                    id={`proxy-app-${i}`}
                    data-testid={`proxy-app-${r.name}`}
                    checked={chosen.has(r.name.toLowerCase())}
                    onCheckedChange={(on) =>
                      setChosen((prev) => {
                        const next = new Set(prev)
                        if (on) next.add(r.name.toLowerCase())
                        else next.delete(r.name.toLowerCase())
                        return next
                      })
                    }
                  />
                  <FieldLabel htmlFor={`proxy-app-${i}`} className="font-mono font-normal">
                    {r.name}
                  </FieldLabel>
                  {r.count > 1 && <span className="text-muted-foreground">×{fmtNum(r.count)}</span>}
                </Field>
              ))}
            </FieldGroup>
          )}
        </FieldGroup>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button data-testid="proxy-apps-save" onClick={save}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
