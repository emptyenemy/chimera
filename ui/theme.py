"""Тема оформления: какая из двух реально нужна сейчас и каким цветом залить окно.

В config.json ключ theme — "system" | "light" | "dark". Тут он превращается в
"light"/"dark" (для "system" — по настройке Windows) и в цвет фона окна, общий
для всех движков (backend_qt, backend_webview, backend_browser), чтобы они не
расходились. Класс темы ставится на <html> до первой отрисовки страницы
(boot_script) — без мигания чужой темой.
"""

from modules import appconfig

# фон окна до загрузки страницы — тот же, что --background темы фронта
WINDOW_BG = {"dark": "#0a0a0a", "light": "#ffffff"}
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _system_theme() -> str:
    """Тема приложений Windows; вне Windows или при ошибке чтения — тёмная."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if light else "dark"
    except (ImportError, OSError, ValueError, AttributeError):
        return "dark"


def resolve_theme(setting: str | None = None) -> str:
    """"light" или "dark". Без аргумента берёт настройку theme из config.json."""
    if setting is None:
        setting = appconfig.load().get("theme")
    if setting in WINDOW_BG:
        return setting
    return _system_theme()  # "system" и любое незнакомое значение


def window_bg(setting: str | None = None) -> str:
    """Цвет фона окна для выбранной (или текущей) темы."""
    return WINDOW_BG[resolve_theme(setting)]


def boot_script(mode: str) -> str:
    """JS, ставящий тему на <html>: атрибут data-theme и класс dark (для shadcn)."""
    cls = 'classList.add("dark")' if mode == "dark" else 'classList.remove("dark")'
    # documentElement может быть null (Qt зовёт скрипт на DocumentCreation): тогда ждём разбора страницы
    return ('(function(){function a(){var r=document.documentElement;if(!r)return;'
            f'r.setAttribute("data-theme","{mode}");r.{cls};'
            f'r.style.colorScheme="{mode}";return 1;}}'
            'if(!a())document.addEventListener("DOMContentLoaded",a);})();')
