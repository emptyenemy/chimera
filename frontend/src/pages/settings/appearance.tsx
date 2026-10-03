import { useEffect, useState } from "react"
import {
  CircleAlertIcon,
  PaletteIcon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { t } from "@/lib/i18n"
import { fmtNum } from "@/lib/format"
import { notify } from "@/lib/notify"
import {
  applyAppearance,
  discardAppearancePreview,
  previewAppearance,
  refreshAppearanceCatalog,
  THEME_SETTINGS,
  useAppearance,
  useAppearancePending,
  type ThemeSetting,
} from "@/lib/theme"

function HueField({ disabled }: { disabled: boolean }) {
  const state = useAppearance()
  const [draft, setDraft] = useState<number | null>(null)
  const hue = draft ?? state?.hue ?? 0
  return (
    <Field>
      <FieldLabel htmlFor="appearance-hue">
        {t("settings.appearance.hue")} · {hue}°
      </FieldLabel>
      <Slider
        id="appearance-hue"
        aria-label={t("settings.appearance.hue")}
        value={[hue]}
        min={0}
        max={359}
        step={1}
        disabled={disabled}
        data-testid="appearance-hue"
        onPointerCancel={() => {
          void discardAppearancePreview().finally(() => setDraft(null))
        }}
        onValueChange={(value) => {
          const next = Array.isArray(value) ? value[0] : value
          setDraft(next)
          void previewAppearance({ hue: next }).catch(() => {})
        }}
        onValueCommitted={(value) => {
          const next = Array.isArray(value) ? value[0] : value
          void applyAppearance({ hue: next }).finally(() => setDraft(null))
        }}
      />
    </Field>
  )
}

export function AppearanceCard() {
  const state = useAppearance()
  const pending = useAppearancePending()
  const [color, setColor] = useState("")
  const [name, setName] = useState("")
  const [refreshing, setRefreshing] = useState(false)
  const [invalid, setInvalid] = useState<string | null>(null)
  useEffect(() => () => { void discardAppearancePreview() }, [])
  const appearance = state?.settings.appearance
  const custom = state?.settings.appearance_custom
  const windows = appearance?.accent_source === "windows"
  const busy = pending || refreshing
  const options =
    state?.themes.map((entry) => ({
      value: entry.id,
      label:
        entry.id === "classic" ? t("settings.appearance.classic") : entry.name,
    })) ?? []
  if (custom)
    options.push({
      value: "personal",
      label: t("settings.appearance.personal", {
        name: custom.appearance.name,
      }),
    })

  async function refreshCatalog() {
    setRefreshing(true)
    try {
      const error = await refreshAppearanceCatalog()
      if (error) notify.error(t("settings.appearance.catalogFailed"), error)
      else notify.success(t("settings.appearance.catalogUpdated"))
    } catch (e) {
      notify.error(t("settings.appearance.catalogFailed"), String(e))
    } finally {
      setRefreshing(false)
    }
  }
  async function checkColor() {
    setInvalid(null)
    try {
      await previewAppearance({
        appearance: { accent: color.trim(), accent_source: "custom" },
      })
    } catch (e) {
      setInvalid(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <Card data-testid="settings-theme">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PaletteIcon className="size-4 text-muted-foreground" />
          {t("settings.appearance.title")}
        </CardTitle>
        <CardDescription>
          {t("settings.appearance.description")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!state || !appearance ? (
          <Skeleton className="h-64" />
        ) : (
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="appearance-palette">
                {t("settings.appearance.palette")}
              </FieldLabel>
              <Select
                items={options}
                value={
                  appearance.name && custom?.appearance.name === appearance.name
                    ? "personal"
                    : appearance.palette
                }
                disabled={busy}
                onValueChange={(value) => {
                  if (value === "personal" && custom)
                    void applyAppearance(custom)
                  else {
                    const entry = state.themes.find(
                      (entry) => entry.id === value
                    )
                    if (entry)
                      void applyAppearance({
                        theme: entry.id === "classic" ? "system" : entry.mode,
                        appearance: {
                          palette: entry.id,
                          name: "",
                          accent: null,
                          accent_source: windows ? "windows" : "palette",
                        },
                      })
                  }
                }}
              >
                <SelectTrigger
                  id="appearance-palette"
                  data-testid="appearance-palette"
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {options.map((option) => (
                      <SelectItem
                        key={option.value}
                        value={option.value}
                        data-testid={`appearance-palette-${option.value}`}
                      >
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                {t("settings.appearance.paletteHint")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel>{t("settings.theme.label")}</FieldLabel>
              <ToggleGroup
                variant="outline"
                value={[state.settings.theme]}
                disabled={busy}
                data-testid="settings-theme-group"
                aria-label={t("settings.theme.label")}
                onValueChange={(values) => {
                  if (values[0])
                    void applyAppearance({ theme: values[0] as ThemeSetting })
                }}
              >
                {THEME_SETTINGS.map((mode) => (
                  <ToggleGroupItem
                    key={mode}
                    value={mode}
                    data-testid={`settings-theme-${mode}`}
                  >
                    {t(`settings.theme.${mode}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            <Field orientation="horizontal">
              <FieldLabel htmlFor="appearance-windows">
                {t("settings.appearance.windows")}
              </FieldLabel>
              <Switch
                id="appearance-windows"
                checked={windows}
                disabled={busy}
                data-testid="appearance-windows"
                onCheckedChange={(on) =>
                  void applyAppearance({
                    appearance: {
                      accent_source: on
                        ? "windows"
                        : appearance.accent
                          ? "custom"
                          : "palette",
                    },
                  })
                }
              />
            </Field>
            {windows && !state.windows_available && (
              <Alert>
                <CircleAlertIcon />
                <AlertDescription>
                  {t("settings.appearance.windowsFallback")}
                </AlertDescription>
              </Alert>
            )}
            <Field>
              <FieldLabel>{t("settings.appearance.accent")}</FieldLabel>
              <ToggleGroup
                variant="outline"
                className="flex-wrap justify-start"
                disabled={busy || windows}
                aria-label={t("settings.appearance.accent")}
                value={appearance.accent_source === "custom"
                  ? state.presets.filter((preset) => Math.min(Math.abs(preset.hue - state.hue), 360 - Math.abs(preset.hue - state.hue)) <= 1).map((preset) => preset.id)
                  : []}
                onValueChange={(values) => {
                  const preset = state.presets.find(
                    (item) => item.id === values[0]
                  )
                  if (preset) void applyAppearance({ hue: preset.hue })
                }}
              >
                {state.presets.map((preset) => (
                  <ToggleGroupItem
                    key={preset.id}
                    value={preset.id}
                    data-testid={`appearance-accent-${preset.id}`}
                    aria-label={t(`settings.appearance.accent.${preset.id}`)}
                  >
                    <span
                      aria-hidden
                      className="size-3 rounded-full"
                      style={{ backgroundColor: preset.color }}
                    />
                    {t(`settings.appearance.accent.${preset.id}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <FieldDescription>
                {t("settings.appearance.accentHint")}
              </FieldDescription>
            </Field>
            <HueField disabled={busy || windows} />
            <Field data-invalid={!!invalid}>
              <FieldLabel htmlFor="appearance-color">
                {t("settings.appearance.customColor")}
              </FieldLabel>
              <Input
                id="appearance-color"
                value={color}
                placeholder={state.accent}
                maxLength={20}
                disabled={busy || windows}
                aria-invalid={!!invalid}
                onChange={(event) => {
                  setColor(event.target.value)
                  setInvalid(null)
                }}
                data-testid="appearance-color"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={busy || windows || !color.trim()}
                  onClick={() => void checkColor()}
                  data-testid="appearance-check"
                >
                  {t("settings.appearance.check")}
                </Button>
                <Button
                  disabled={busy || windows || !color.trim() || !!invalid}
                  onClick={() =>
                    void applyAppearance({
                      appearance: {
                        accent: color.trim(),
                        accent_source: "custom",
                      },
                    })
                  }
                  data-testid="appearance-color-apply"
                >
                  {t("settings.appearance.applyAccent")}
                </Button>
              </div>
              {invalid && <FieldDescription>{invalid}</FieldDescription>}
            </Field>
            {state.normalized && (
              <Alert data-testid="appearance-normalized">
                <CircleAlertIcon />
                <AlertDescription>
                  {t("settings.appearance.normalized")}
                </AlertDescription>
              </Alert>
            )}
            {state.contrast_adjusted && (
              <Alert data-testid="appearance-contrast-warning">
                <CircleAlertIcon />
                <AlertTitle>
                  {t("settings.appearance.contrastWarning")}
                </AlertTitle>
                <AlertDescription>
                  <p>
                    {t("settings.appearance.contrastHint", {
                      color: state.accent,
                    })}
                  </p>
                  <Button
                    variant="outline"
                    disabled={busy || windows}
                    data-testid="appearance-accept"
                    onClick={() =>
                      void applyAppearance({
                        appearance: {
                          accent: state.accent,
                          accent_source: "custom",
                        },
                      })
                    }
                  >
                    {t("settings.appearance.accept")}
                  </Button>
                </AlertDescription>
              </Alert>
            )}
            <FieldDescription data-testid="appearance-contrast">
              {t("settings.appearance.contrast", {
                text: fmtNum(state.contrast.text),
                background: fmtNum(state.contrast.background),
                color: state.accent,
              })}
            </FieldDescription>
            <Field>
              <FieldLabel>{t("settings.appearance.radius")}</FieldLabel>
              <ToggleGroup
                value={[appearance.radius]}
                className="max-w-full flex-wrap justify-start"
                aria-label={t("settings.appearance.radius")}
                variant="outline"
                disabled={busy}
                onValueChange={(values) => {
                  if (values[0])
                    void applyAppearance({
                      appearance: {
                        radius: values[0] as typeof appearance.radius,
                      },
                    })
                }}
              >
                {(["square", "default", "rounded"] as const).map((radius) => (
                  <ToggleGroupItem
                    value={radius}
                    key={radius}
                    data-testid={`appearance-radius-${radius}`}
                  >
                    {t(`settings.appearance.radius.${radius}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            <Field>
              <FieldLabel>{t("settings.appearance.density")}</FieldLabel>
              <ToggleGroup
                value={[appearance.density]}
                aria-label={t("settings.appearance.density")}
                variant="outline"
                disabled={busy}
                onValueChange={(values) => {
                  if (values[0])
                    void applyAppearance({
                      appearance: {
                        density: values[0] as typeof appearance.density,
                      },
                    })
                }}
              >
                {(["comfortable", "compact"] as const).map((density) => (
                  <ToggleGroupItem
                    value={density}
                    key={density}
                    data-testid={`appearance-density-${density}`}
                  >
                    {t(`settings.appearance.density.${density}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            <Field>
              <FieldLabel htmlFor="appearance-name">
                {t("settings.appearance.saveOwn")}
              </FieldLabel>
              <Input
                id="appearance-name"
                value={name}
                placeholder={t("settings.appearance.name")}
                onChange={(event) => setName(event.target.value)}
                disabled={busy}
                maxLength={60}
                data-testid="appearance-name"
              />
              <Button
                disabled={busy || !name.trim()}
                data-testid="appearance-save"
                onClick={() => {
                  const variant = {
                    theme: state.settings.theme,
                    appearance: { ...appearance, name: name.trim() },
                  }
                  void applyAppearance({
                    ...variant,
                    appearance_custom: variant,
                  })
                }}
              >
                <SaveIcon data-icon="inline-start" />
                {t("settings.appearance.save")}
              </Button>
            </Field>
          </FieldGroup>
        )}
      </CardContent>
      <CardFooter>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void refreshCatalog()}
          data-testid="appearance-refresh"
        >
          {refreshing ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <RefreshCwIcon data-icon="inline-start" />
          )}
          {t("settings.appearance.refresh")}
        </Button>
      </CardFooter>
    </Card>
  )
}
