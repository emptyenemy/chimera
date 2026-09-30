"""Curated palette, safe accent, cache and legacy configuration contracts."""

import colorsys
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from modules import appconfig, appearance as a, paths
from ui import theme


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")


PALETTES = [entry["id"] for entry in a.catalog()["themes"]]


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_default_palette_readability(palette, mode):
    result = a.state({"theme": mode, "appearance": {"palette": palette}})
    assert result["contrast"]["text"] >= 4.5 and result["contrast"]["background"] >= 4.5


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("preset", list(a.PRESET_HUES))
def test_presets_readable_and_surfaces_immutable(palette, mode, preset):
    entry = next(e for e in a.catalog()["themes"] if e["id"] == palette)
    config = {"theme": mode, "appearance": {"palette": palette, "accent_source": "custom", "accent": a.hue_color(a.PRESET_HUES[preset])}}
    result = a.state(config)
    styles = result["styles"]
    accent = result["accent"]
    text = styles["--primary-foreground"]
    assert a.contrast(text, accent) >= 4.5
    for surface in ("background", "card", "popover", "sidebar"):
        bg = styles[f"--{surface}"]
        assert bg == entry[mode]["tokens"][f"--color-{surface}"]
        assert a.contrast(accent, bg) >= 4.5
        assert a.contrast(text, a.blend(accent, bg, .8)) >= 4.5
    assert {k for k in styles if k.startswith("--color-")} == a.COLOR_TOKENS
    for name in ("primary", "ring", "sidebar-primary", "sidebar-ring", "chart-1"):
        assert styles[f"--{name}"] == accent
    assert styles["--accent"] == styles["--sidebar-accent"] == a.blend(accent, styles["--background"], .15)
    _, lightness, saturation = colorsys.rgb_to_hls(*a.rgb(accent))
    assert a.S_MIN <= saturation <= a.S_MAX and a.L_MIN <= lightness <= a.L_MAX


@pytest.mark.parametrize("color", ["#00ff00", "#ff00ff", "#010101", "#ffffff", "#000", "#fefefe"])
def test_color_clamps_idempotently_and_reports(color):
    normalized, changed = a.normalize_color(color)
    assert changed
    _, lightness, saturation = colorsys.rgb_to_hls(*a.rgb(normalized))
    assert a.S_MIN <= saturation <= a.S_MAX and a.L_MIN <= lightness <= a.L_MAX
    assert a.normalize_color(normalized) == (normalized, False)
    result = a.preview({"theme": "dark"}, {"appearance": {"accent": color, "accent_source": "custom"}})
    assert result["normalized"] and result["contrast"]["text"] >= 4.5 and result["contrast"]["background"] >= 4.5


@pytest.mark.parametrize("key", ["background", "sidebar", "panel", "card", "primary", "hover", "active", "ring",
                                 "chart-1", "sidebar-primary", "--color-background"])
def test_cannot_set_surfaces_or_derived_tokens(key):
    assert key not in a.DEFAULTS and key not in appconfig.DEFAULTS
    for action in (lambda: a.normalize_settings({key: "#abcdef"}), lambda: a.merged({}, {key: "#abcdef"}),
                   lambda: appconfig.set_value(key, "#abcdef")):
        with pytest.raises(ValueError):
            action()
    assert not appconfig.CONFIG_PATH.exists()


@pytest.mark.parametrize("mode", ["light", "dark", "system"])
def test_old_theme_only_config_and_boot(mode):
    original = json.dumps({"theme": mode}).encode()
    appconfig.CONFIG_PATH.write_bytes(original)
    config = appconfig.load()
    assert config["appearance"] == a.DEFAULTS and config["appearance_custom"] is None
    result = a.state(config)
    assert result["palette"] == "classic"
    assert appconfig.CONFIG_PATH.read_bytes() == original
    assert theme.window_bg() == theme.WINDOW_BG[theme.resolve_theme(mode)]
    from ui.backend_browser import _mark_page
    page = _mark_page(b"<html><head></head><body></body></html>", "token", result["mode"], native=True)
    assert page.index(b"__CHIMERA_APPEARANCE__") < page.index(b"</head>")
    assert b"httpBridge" not in page


def test_catalog_validates_exact_current_css_tokens():
    from pathlib import Path
    import re
    css = (Path(__file__).resolve().parents[1] / "frontend/src/index.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"(--color-[\w-]+):", css))
    assert declared == a.COLOR_TOKENS
    assert len(PALETTES) == 14
    assert a.validate_catalog(deepcopy(a.catalog()))


def test_refresh_installs_theme_keeps_removed_and_rejects_css():
    data = deepcopy(a.catalog())
    entry = deepcopy(data["themes"][1])
    entry["id"], entry["name"] = "test-new", "New curated theme"
    incoming = {"schema": 1, "themes": [entry]}
    assert a.refresh_catalog(lambda url: json.dumps(incoming).encode())["updated"]
    assert a.state({"theme": "dark", "appearance": {"palette": "test-new"}})["palette"] == "test-new"
    cache = paths.DATA_DIR / "themes/catalog.json"
    previous = cache.read_bytes()
    incoming["themes"][0]["dark"]["tokens"]["--color-background"] = "url(https://example.org)"
    assert not a.refresh_catalog(lambda url: json.dumps(incoming).encode())["updated"]
    assert cache.read_bytes() == previous
    assert a.refresh_catalog(lambda url: a.BUNDLED.read_bytes())["updated"]
    assert "test-new" in {e["id"] for e in a.catalog()["themes"]}
    assert not a.refresh_catalog(lambda url: b"x" * (a.MAX_BYTES + 1))["updated"]


@pytest.mark.parametrize("failure", ["unknown-token", "bad-contrast", "license", "mode", "schema"])
def test_invalid_catalog_falls_back(failure):
    data = deepcopy(a.catalog())
    if failure == "unknown-token":
        data["themes"][0]["dark"]["tokens"]["--new"] = "#000000"
    elif failure == "bad-contrast":
        data["themes"][0]["dark"]["tokens"]["--color-foreground"] = "#0a0a0a"
    elif failure == "license":
        data["themes"][0]["license"] = "proprietary"
    elif failure == "mode":
        data["themes"][0]["mode"] = "script"
    else:
        data["schema"] = 2
    with pytest.raises(ValueError):
        a.validate_catalog(data)
    cache = paths.DATA_DIR / "themes/catalog.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(data))
    assert a.catalog() == a._json_file(a.BUNDLED)


def test_windows_accent_abgr_and_fallback(monkeypatch):
    key = SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: False)
    class Key:
        def __enter__(self):
            return key

        def __exit__(self, *args):
            return False
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=lambda *args: Key(), QueryValueEx=lambda *args: (0xff563412, 4))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert a.windows_accent() == ("#123456", True)
    result = a.state({"theme": "dark", "appearance": {"accent_source": "windows"}})
    assert result["windows_available"] and result["contrast"]["text"] >= 4.5
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert a.windows_accent()[1] is False


def test_saved_personal_variant_and_whole_system_mode(monkeypatch):
    variant = {"theme": "system", "appearance": {"palette": "catppuccin-mocha", "name": "Personal", "accent_source": "custom", "accent": "#5288cf"}}
    config = a.merged({}, {**variant, "appearance_custom": variant})
    appconfig.restore_values(config)
    loaded = appconfig.load()
    assert loaded["appearance_custom"]["appearance"]["name"] == "Personal"
    assert a.state(loaded, "light")["mode"] == "light"
    assert a.state(loaded, "dark")["mode"] == "dark"
    assert a.state(loaded, "light")["styles"]["--background"] != a.state(loaded, "dark")["styles"]["--background"]
    assert a.state({"theme": "dark", "appearance": loaded["appearance"]}, "light")["mode"] == "dark"


@pytest.mark.parametrize("hue", [-1, 360, True, "red", float("nan")])
def test_invalid_virtual_hue(hue):
    with pytest.raises(ValueError):
        a.merged({}, {"hue": hue})
