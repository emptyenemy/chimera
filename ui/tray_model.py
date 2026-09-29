"""Что показывает и что умеет трей — без Qt, чтобы проверялось тестами.

Состояние берётся из снимка хаба (ui/hub.py: {ключ модуля: данные}) — того же,
что видит окно. Правила «включён ли модуль» и «защита активна» повторяют
ui/web/js/shell.js (Status), команды — дашборд (ui/web/js/pages/dashboard.js):
трей, сайдбар и дашборд не должны расходиться в том, что считать включённым.

Тексты меню и уведомлений — в каталоге (ключи tray.*), язык берётся в момент показа.
"""

from modules import errors
from modules.errors import ChimeraError
from modules.i18n import t

# (ключ источника хаба, ключ подписи в каталоге)
MODULES = (
    ("winws", "tray.module.winws"),
    ("proxy", "tray.module.proxy"),
    ("tg", "tray.module.tg"),
    ("hosts", "tray.module.hosts"),
)


PANIC_COMMAND = ("panic_all", [])   # тот же метод Api, что у кнопки на «Обзоре»


def module_label(key: str) -> str:
    return t(dict(MODULES)[key])


def panic_label() -> str:
    return t("tray.panic")


def panic_summary(data: dict | None) -> str | None:
    """Текст уведомления о шагах «Выключить всё», которые не получились; None — всё выключено."""
    failed = [s for s in (data or {}).get("steps") or [] if not s.get("ok")]
    if not failed:
        return None
    return "\n".join(f"{s.get('step')}: {errors.localized(s)}" for s in failed)


def is_on(key: str, data: dict | None) -> bool:
    if not data:
        return False
    return bool(data.get("applied") if key == "hosts" else data.get("running"))


def summary(states: dict) -> tuple[bool, int, str]:
    """(защита активна, сколько модулей включено, строка состояния)."""
    on = {key: is_on(key, states.get(key)) for key, _ in MODULES}
    n = sum(on.values())
    # «защита» — любой способ обхода, который реально трогает трафик (tg — нет)
    guard = on["winws"] or on["proxy"] or on["hosts"]
    total = len(MODULES)
    text = (t("tray.summary.guard", n=n, total=total) if guard
            else (t("tray.summary.some", n=n, total=total) if n else t("tray.summary.off")))
    return guard, n, text


def winws_strategy(data: dict | None) -> str | None:
    """Какую стратегию запускать из трея: текущую, последнюю или первую в списке."""
    if not data:
        return None
    first = (data.get("strategies") or [{}])[0].get("id")
    return data.get("current") or data.get("last_strategy") or first


def toggle_command(key: str, data: dict | None, on: bool) -> tuple[str, list]:
    """(метод Api, аргументы), который включает (on) или выключает модуль."""
    if key == "winws":
        if not on:
            return "winws_stop", []
        strategy = winws_strategy(data)
        if not strategy:
            raise ChimeraError("err.strategies.none")
        return "winws_start", [strategy]
    if key == "hosts":
        return "hosts_set_enabled", [on]
    if key in ("proxy", "tg"):
        return f"{key}_{'start' if on else 'stop'}", []
    raise KeyError(key)
