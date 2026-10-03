import { useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
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
import { dismissDialog, useDialogRequest, type DialogRequest } from "@/lib/dialogs"
import { t } from "@/lib/i18n"

type Confirm = Extract<DialogRequest, { kind: "confirm" }>
type Prompt = Extract<DialogRequest, { kind: "prompt" }>

function ConfirmView({ req }: { req: Confirm }) {
  const { opts } = req
  const settle = (ok: boolean) => {
    req.resolve(ok)
    dismissDialog(req)
  }
  return (
    <AlertDialog open onOpenChange={(open) => !open && settle(false)}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{opts.title}</AlertDialogTitle>
          {opts.description && <AlertDialogDescription>{opts.description}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="confirm-cancel">{opts.cancelText ?? t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            data-testid="confirm-ok"
            variant={opts.destructive ? "destructive" : "default"}
            onClick={() => settle(true)}
          >
            {opts.confirmText ?? t("common.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function PromptView({ req }: { req: Prompt }) {
  const { opts } = req
  const [value, setValue] = useState(opts.value ?? "")
  const settle = (result: string | null) => {
    req.resolve(result)
    dismissDialog(req)
  }
  return (
    <Dialog open onOpenChange={(open) => !open && settle(null)}>
      <DialogContent data-testid="prompt-dialog">
        <form
          className="grid gap-6"
          onSubmit={(e) => {
            e.preventDefault()
            settle(value)
          }}
        >
          <DialogHeader>
            <DialogTitle>{opts.title}</DialogTitle>
            {opts.description && <DialogDescription>{opts.description}</DialogDescription>}
          </DialogHeader>
          <FieldGroup>
            <Field>
              {opts.label && <FieldLabel htmlFor="prompt-input">{opts.label}</FieldLabel>}
              <Input
                id="prompt-input"
                data-testid="prompt-input"
                autoFocus
                className={opts.mono ? "font-mono" : undefined}
                value={value}
                placeholder={opts.placeholder}
                aria-label={opts.label ? undefined : opts.title}
                onChange={(e) => setValue(e.target.value)}
              />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => settle(null)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" data-testid="prompt-ok">
              {opts.confirmText ?? t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Показывает первый диалог из очереди confirmDialog()/promptDialog(). */
export function DialogHost() {
  const req = useDialogRequest()
  if (!req) return null
  return req.kind === "confirm" ? <ConfirmView key={req.id} req={req} /> : <PromptView key={req.id} req={req} />
}
