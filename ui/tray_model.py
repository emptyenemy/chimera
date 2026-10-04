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


# семейство строк `chimera fix`: способ починки по его виду (strategy, hosts, dns, proxy)
FIX_VIA = "cli.fix.via"


class AutotuneNews:
    """Итог самолечения в фоне (modules/autotune/watch.py) — одно уведомление на сессию.

    Окно в это время обычно закрыто в трей, а подбор меняет систему: человек должен узнать,
    что и чем Chimera починила сама. Сессии, закончившиеся до запуска трея, не показываются."""

    def __init__(self):
        self.seen = None
        self.started = False

    def update(self, state: dict | None) -> tuple[str, str] | None:
        """(заголовок, текст) нового итога или None. state — источник хаба autotune."""
        state = state or {}
        session = state.get("active") or state.get("last")
        if not self.started:
            self.started = True
            # идущий сейчас подбор ещё закончится — его итог покажем
            if session and session.get("phase") != "running":
                self.seen = session.get("id")
            return None
        if (not session or session.get("trigger") != "watch" or session.get("phase") != "done"
                or session.get("id") == self.seen):
            return None
        self.seen = session.get("id")
        rows = [r for r in (session.get("report") or {}).get("services") or [] if not r.get("skipped")]
        fixed = [r for r in rows if r.get("fix") and (r.get("after") or {}).get("ok")]
        broken = [r for r in rows if not (r.get("after") or {}).get("ok")]
        lines = [t("tray.autotune.row_fixed", name=r["name"], via=t(f"{FIX_VIA}.{r['fix']['kind']}", id=r["fix"]["id"]))
                 for r in fixed]
        lines += [t("tray.autotune.row_broken", name=r["name"]) for r in broken]
        title = t("tray.autotune.fixed") if fixed and not broken else (
            t("tray.autotune.partly") if fixed else t("tray.autotune.failed"))
        return title, "\n".join(lines)
