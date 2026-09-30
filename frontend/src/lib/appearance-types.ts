export interface AppearanceSettings {
  palette: string
  accent: string | null
  accent_source: "palette" | "custom" | "windows"
  radius: "square" | "default" | "rounded"
  density: "comfortable" | "compact"
  name: string
}

export interface AppearanceState {
  settings: {
    theme: "system" | "light" | "dark"
    appearance: AppearanceSettings
    appearance_custom?: {
      theme: "system" | "light" | "dark"
      appearance: AppearanceSettings
    } | null
  }
  mode: "light" | "dark"
  palette: string
  styles: Record<string, string>
  accent: string
  hue: number
  normalized: boolean
  contrast_adjusted: boolean
  windows_available: boolean
  contrast: { text: number; background: number; requested: number | null }
  themes: { id: string; name: string; mode: "light" | "dark" }[]
  presets: { id: string; color: string; hue: number }[]
}

export interface AppearancePatch {
  hue?: number
  theme?: "system" | "light" | "dark"
  appearance?: Partial<AppearanceSettings>
  appearance_custom?: {
    theme: "system" | "light" | "dark"
    appearance: AppearanceSettings
  } | null
}
