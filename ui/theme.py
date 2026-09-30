"""Resolve the Windows mode and apply the entire palette before first paint."""

import json

from modules import appconfig, appearance

WINDOW_BG = {"dark": "#0a0a0a", "light": "#ffffff"}
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _system_theme() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if light else "dark"
    except (ImportError, OSError, ValueError, AttributeError):
        return "dark"


def resolve_theme(setting: str | None = None) -> str:
    if setting is None:
        setting = appconfig.load().get("theme")
    return setting if setting in WINDOW_BG else _system_theme()


def window_bg(setting: str | None = None) -> str:
    config = appconfig.load()
    if setting is not None:
        config = {**config, "theme": resolve_theme(setting)}
    return appearance.state(config)["styles"]["--background"]


def boot_script(mode: str) -> str:
    config = appconfig.load()
    payload = appearance.state({**config, "theme": mode})
    payload["settings"]["theme"] = config.get("theme", "system")
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    cls = 'classList.add("dark")' if mode == "dark" else 'classList.remove("dark")'
    return ('(function(){var p=' + data + ';window.__CHIMERA_APPEARANCE__=p;'
            'function a(){var r=document.documentElement;if(!r)return;'
            f'r.setAttribute("data-theme","{mode}");r.{cls};'
            f'r.style.colorScheme="{mode}";'
            'r.dataset.palette=p.palette;'
            'Object.keys(p.styles).forEach(function(k){r.style.setProperty(k,p.styles[k]);});return 1;}'
            'if(!a()){var o=new MutationObserver(function(){if(a())o.disconnect();});'
            'o.observe(document,{childList:true,subtree:true});'
            'document.addEventListener("DOMContentLoaded",function(){a();o.disconnect();});}})();')
