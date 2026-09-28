"""Что показывает и что умеет трей — без Qt, чтобы проверялось тестами.

Состояние берётся из снимка хаба (ui/hub.py: {ключ модуля: данные}) — того же,
что видит окно. Правила «включён ли модуль» и «защита активна» повторяют
ui/web/js/shell.js (Status), команды — дашборд (ui/web/js/pages/dashboard.js):
трей, сайдбар и дашборд не должны расходиться в том, что считать включённым.
"""

# (ключ источника хаба, подпись в меню)
MODULES = (
    ("winws", "Обход DPI"),
    ("proxy", "Прокси"),
    ("tg", "Telegram-прокси"),
    ("hosts", "Разблокировка hosts"),
)


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
    text = f"Защита активна · {n} из {total}" if guard else (f"{n} из {total} включено" if n else "Всё выключено")
    return guard, n, text


def tooltip(states: dict) -> str:
    return f"Chimera — {summary(states)[2].lower()}" if states else "Chimera"


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
            raise ValueError("Нет стратегий — выбери одну во вкладке «Стратегии»")
        return "winws_start", [strategy]
    if key == "hosts":
        return "hosts_set_enabled", [on]
    if key in ("proxy", "tg"):
        return f"{key}_{'start' if on else 'stop'}", []
    raise KeyError(key)
