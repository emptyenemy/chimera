"""Whole curated palettes and one bounded accent; no per-surface user settings."""

import colorsys
import json
import re
import threading
import urllib.request
from functools import lru_cache
from itertools import product
from pathlib import Path

from modules import paths
from modules.errors import ChimeraValueError
from modules.fileutil import atomic_write_text
from modules.i18n import t

CATALOG_URL = "https://raw.githubusercontent.com/emptyenemy/chimera/main/themes/catalog.json"
BUNDLED = Path(__file__).resolve().parent.parent / "themes" / "catalog.json"
MAX_BYTES = 1024 * 1024
COLOR_NAMES = tuple("success warning info sidebar-ring sidebar-border sidebar-accent-foreground sidebar-accent "
                    "sidebar-primary-foreground sidebar-primary sidebar-foreground sidebar chart-5 chart-4 chart-3 "
                    "chart-2 chart-1 ring input border destructive accent-foreground accent muted-foreground muted "
                    "secondary-foreground secondary primary-foreground primary popover-foreground popover "
                    "card-foreground card foreground background".split())
COLOR_TOKENS = frozenset(f"--color-{name}" for name in COLOR_NAMES)
DEFAULTS = {"palette": "classic", "accent": None, "accent_source": "palette", "radius": "default",
            "density": "comfortable", "name": ""}
PRESET_HUES = {"red": 0, "orange": 25, "amber": 45, "yellow": 60, "lime": 85, "green": 140,
               "teal": 175, "cyan": 195, "blue": 215, "indigo": 245, "violet": 275, "pink": 330}
S_MIN, S_MAX, L_MIN, L_MAX = .45, .70, .20, .80
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_LOCK = threading.RLock()


def rgb(color):
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def hex_rgb(value):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in value)


def hue_color(hue, lightness=.50, saturation=.60):
    return hex_rgb(colorsys.hls_to_rgb((hue % 360) / 360, lightness, saturation))


def normalize_color(value):
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{3}", value.strip()):
        value = "#" + "".join(c * 2 for c in value.strip()[1:])
    if not isinstance(value, str) or not _HEX.fullmatch(value.strip()):
        raise ChimeraValueError("err.appearance.color")
    value = value.strip().lower()
    h, lightness, saturation = colorsys.rgb_to_hls(*rgb(value))
    if L_MIN <= lightness <= L_MAX and S_MIN <= saturation <= S_MAX:
        return value, False
    target = colorsys.hls_to_rgb(h, max(L_MIN, min(L_MAX, lightness)), max(S_MIN, min(S_MAX, saturation)))
    # Hex quantization must keep the actual stored color inside the corridor.
    rounded = [round(c * 255) for c in target]
    candidates = []
    for offsets in product(range(-2, 3), repeat=3):
        channels = tuple(max(0, min(255, c + offset)) / 255 for c, offset in zip(rounded, offsets, strict=True))
        _, candidate_l, candidate_s = colorsys.rgb_to_hls(*channels)
        if L_MIN <= candidate_l <= L_MAX and S_MIN <= candidate_s <= S_MAX:
            candidates.append(channels)
    result = hex_rgb(min(candidates, key=lambda candidate: sum((a - b) ** 2 for a, b in zip(candidate, target, strict=True))))
    return result, result != value


def luminance(color):
    values = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb(color)]
    return sum(a * b for a, b in zip(values, (.2126, .7152, .0722), strict=True))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def blend(a, b, amount):
    return hex_rgb(tuple(x * amount + y * (1 - amount) for x, y in zip(rgb(a), rgb(b), strict=True)))


def foreground(color):
    return max(("#000000", "#ffffff"), key=lambda candidate: contrast(candidate, color))


def _readable(color, surfaces):
    text = foreground(color)
    return (all(contrast(color, bg) >= 4.5 for bg in surfaces)
            and all(contrast(text, blend(color, bg, .8)) >= 4.5 for bg in surfaces)
            and contrast(text, color) >= 4.5)


def safe_accent(value, surfaces):
    normalized, clamped = normalize_color(value)
    if _readable(normalized, surfaces):
        return normalized, clamped, False
    hue, lightness, saturation = colorsys.rgb_to_hls(*rgb(normalized))
    candidates = [hex_rgb(colorsys.hls_to_rgb(hue, n / 1000, saturation)) for n in range(200, 801)]
    valid = [c for c in candidates if normalize_color(c)[0] == c and _readable(c, surfaces)]
    if not valid:
        raise ChimeraValueError("err.appearance.contrast")
    chosen = min(valid, key=lambda c: abs(colorsys.rgb_to_hls(*rgb(c))[1] - lightness))
    return chosen, clamped, True


def validate_catalog(data):
    if not isinstance(data, dict) or set(data) != {"schema", "themes"} or type(data["schema"]) is not int or data["schema"] != 1:
        raise ChimeraValueError("err.appearance.catalog")
    entries = data["themes"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ChimeraValueError("err.appearance.catalog")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "name", "mode", "license", "source", "light", "dark"}:
            raise ChimeraValueError("err.appearance.catalog")
        if (not isinstance(entry["id"], str) or not _ID.fullmatch(entry["id"]) or entry["id"] in seen
                or not isinstance(entry["name"], str) or not 1 <= len(entry["name"]) <= 80
                or entry["mode"] not in ("light", "dark")
                or entry["license"] not in ("MIT", "MIT/X11", "Apache-2.0", "BSD-3-Clause", "CC0-1.0")
                or not isinstance(entry["source"], str) or not entry["source"].startswith("https://") or len(entry["source"]) > 250):
            raise ChimeraValueError("err.appearance.catalog")
        seen.add(entry["id"])
        for mode in ("light", "dark"):
            variant = entry[mode]
            if not isinstance(variant, dict) or set(variant) != {"tokens", "accent"}:
                raise ChimeraValueError("err.appearance.catalog")
            tokens = variant["tokens"]
            if (not isinstance(tokens, dict) or set(tokens) != COLOR_TOKENS
                    or any(not isinstance(c, str) or not _HEX.fullmatch(c) for c in tokens.values())
                    or not isinstance(variant["accent"], str) or not _HEX.fullmatch(variant["accent"])):
                raise ChimeraValueError("err.appearance.catalog")
            for surface, text in (("background", "foreground"), ("card", "card-foreground"),
                                  ("popover", "popover-foreground"), ("sidebar", "sidebar-foreground"),
                                  ("muted", "muted-foreground"), ("secondary", "secondary-foreground")):
                if contrast(tokens[f"--color-{surface}"], tokens[f"--color-{text}"]) < 4.5:
                    raise ChimeraValueError("err.appearance.catalog")
            bg_lum = luminance(tokens["--color-background"])
            if (mode == "dark" and bg_lum > .15) or (mode == "light" and bg_lum < .5):
                raise ChimeraValueError("err.appearance.catalog")
            if entry["id"] != "classic":
                safe_accent(variant["accent"], [tokens[f"--color-{k}"] for k in ("background", "card", "popover", "sidebar")])
    return data


def _json_file(path):
    stat = path.stat()
    return _cached_file(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _cached_file(path, mtime, size):
    if path.stat().st_size > MAX_BYTES:
        raise ChimeraValueError("err.appearance.catalog")
    return validate_catalog(json.loads(path.read_bytes()))


def catalog():
    base = _json_file(BUNDLED)
    cache = paths.DATA_DIR / "themes" / "catalog.json"
    try:
        if cache.is_file() and not cache.is_symlink():
            updated = _json_file(cache)
            entries = {e["id"]: e for e in base["themes"]}
            entries.update({e["id"]: e for e in updated["themes"] if e["id"] != "classic"})
            return {"schema": 1, "themes": list(entries.values())}
    except (OSError, ValueError, TypeError, RecursionError):
        pass
    return base


def refresh_catalog(fetch=None):
    try:
        if fetch is None:
            request = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "Chimera"})
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
        else:
            raw = fetch(CATALOG_URL)
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ChimeraValueError("err.appearance.catalog")
        incoming = validate_catalog(json.loads(raw))
        with _LOCK:
            # Retain installed themes removed from the public index, including the active one.
            merged = {e["id"]: e for e in catalog()["themes"]}
            merged.update({e["id"]: e for e in incoming["themes"] if e["id"] != "classic"})
            final = validate_catalog({"schema": 1, "themes": list(merged.values())})
            directory = paths.DATA_DIR / "themes"
            directory.mkdir(parents=True, exist_ok=True)
            atomic_write_text(directory / "catalog.json", json.dumps(final, ensure_ascii=False, indent=2) + "\n")
        return {"updated": True, "error": None}
    except Exception:
        return {"updated": False, "error": t("err.appearance.catalog_network")}


def normalize_settings(value, *, fallback=False):
    try:
        if not isinstance(value, dict) or set(value) - set(DEFAULTS):
            raise ChimeraValueError("err.appearance.settings")
        result = {**DEFAULTS, **value}
        if (not isinstance(result["palette"], str) or not _ID.fullmatch(result["palette"])
                or result["accent_source"] not in ("palette", "custom", "windows")
                or result["radius"] not in ("square", "default", "rounded")
                or result["density"] not in ("comfortable", "compact")
                or not isinstance(result["name"], str) or len(result["name"]) > 60):
            raise ChimeraValueError("err.appearance.settings")
        if result["accent"] is not None:
            result["accent"] = normalize_color(result["accent"])[0]
        if result["accent_source"] == "custom" and result["accent"] is None:
            raise ChimeraValueError("err.appearance.settings")
        return result
    except (ValueError, TypeError):
        if fallback:
            return dict(DEFAULTS)
        raise ChimeraValueError("err.appearance.settings") from None


def normalize_custom(value, *, fallback=False):
    if value is None:
        return None
    try:
        if (not isinstance(value, dict) or set(value) != {"theme", "appearance"}
                or value["theme"] not in ("system", "light", "dark")):
            raise ChimeraValueError("err.appearance.settings")
        settings = normalize_settings(value["appearance"])
        if not settings["name"].strip():
            raise ChimeraValueError("err.appearance.settings")
        return {"theme": value["theme"], "appearance": settings}
    except (ValueError, TypeError):
        if fallback:
            return None
        raise ChimeraValueError("err.appearance.settings") from None


def windows_accent():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        if type(value) is not int:
            raise ValueError
        return f"#{value & 255:02x}{(value >> 8) & 255:02x}{(value >> 16) & 255:02x}", True
    except (ImportError, OSError, ValueError, AttributeError):
        return "#5288cf", False


def state(config=None, mode=None):
    from modules import appconfig
    from ui.theme import resolve_theme
    config = config if config is not None else appconfig.load()
    settings = normalize_settings(config.get("appearance", {}), fallback=True)
    resolved = mode if config.get("theme", "system") == "system" and mode in ("light", "dark") else resolve_theme(config.get("theme", "system"))
    entries = catalog()["themes"]
    entry = next((e for e in entries if e["id"] == settings["palette"]), entries[0])
    colors = dict(entry[resolved]["tokens"])
    source = entry[resolved]["accent"] if settings["accent_source"] == "palette" else settings["accent"]
    available = True
    if settings["accent_source"] == "windows":
        source, available = windows_accent()
    surfaces = [colors[f"--color-{key}"] for key in ("background", "card", "popover", "sidebar")]
    legacy = entry["id"] == "classic" and settings["accent_source"] == "palette"
    accent, clamped, adjusted = (source, False, False) if legacy else safe_accent(source, surfaces)
    text = foreground(accent)
    for name in ("primary", "ring", "sidebar-primary", "sidebar-ring", "chart-1"):
        colors[f"--color-{name}"] = accent
    for name in ("primary-foreground", "sidebar-primary-foreground"):
        colors[f"--color-{name}"] = text
    if not legacy:
        soft = blend(accent, colors["--color-background"], .15)
        soft_text = colors["--color-foreground"]
        if contrast(soft_text, soft) < 4.5:
            soft_text = foreground(soft)
        for name in ("accent", "sidebar-accent"):
            colors[f"--color-{name}"] = soft
            colors[f"--color-{name}-foreground"] = soft_text
    styles = {**colors, **{"--" + key.removeprefix("--color-"): value for key, value in colors.items()}}
    styles["--radius"] = {"square": "0.125rem", "default": "0.625rem", "rounded": "1rem"}[settings["radius"]]
    styles["--spacing"] = "0.22rem" if settings["density"] == "compact" else "0.25rem"
    return {"settings": {"theme": config.get("theme", "system"), "appearance": settings,
                         "appearance_custom": normalize_custom(config.get("appearance_custom"), fallback=True)}, "mode": resolved,
            "palette": entry["id"], "styles": styles, "accent": accent,
            "hue": round(colorsys.rgb_to_hls(*rgb(accent))[0] * 360), "normalized": clamped,
            "contrast_adjusted": adjusted, "windows_available": available,
            "contrast": {"text": round(contrast(text, accent), 4),
                         "background": round(min(contrast(accent, bg) for bg in surfaces), 4),
                         "requested": round(min(contrast(normalize_color(source)[0], bg) for bg in surfaces), 4) if not legacy else None},
            "themes": [{"id": e["id"], "name": e["name"], "mode": e["mode"]} for e in entries],
            "presets": [{"id": key, "color": hue_color(hue), "hue": hue} for key, hue in PRESET_HUES.items()]}


def preview(config, patch, mode=None):
    result = state(merged(config, patch), mode)
    raw = patch.get("appearance", {}).get("accent")
    if raw is not None:
        result["normalized"] |= normalize_color(raw)[1]
    return result


def merged(config, patch):
    if not isinstance(patch, dict) or set(patch) - {"theme", "appearance", "appearance_custom", "hue"}:
        raise ChimeraValueError("err.appearance.settings")
    result = dict(config)
    if "appearance_custom" in patch:
        result["appearance_custom"] = normalize_custom(patch["appearance_custom"])
    if "theme" in patch:
        if patch["theme"] not in ("system", "light", "dark"):
            raise ChimeraValueError("err.appearance.settings")
        result["theme"] = patch["theme"]
    if "appearance" in patch:
        if not isinstance(patch["appearance"], dict):
            raise ChimeraValueError("err.appearance.settings")
        result["appearance"] = normalize_settings({**normalize_settings(result.get("appearance", {}), fallback=True), **patch["appearance"]})
    if "hue" in patch:
        hue = patch["hue"]
        if type(hue) not in (int, float) or not 0 <= hue <= 359:
            raise ChimeraValueError("err.appearance.settings")
        result["appearance"] = normalize_settings({**result.get("appearance", {}), "accent": hue_color(hue), "accent_source": "custom"})
    return result
