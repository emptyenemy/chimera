"""Терминальный интерфейс (TUI) — режим без окна для запуска из консоли.

curses на Windows нет, поэтому меню — цифрами, в духе service.bat у Flowseal,
но с подсветкой статусов через ANSI-эскейпы (Windows 10+ их понимает; в
legacy-консоли без Windows Terminal явно включаем VT-режим — см. enable_ansi).

Работает через класс Api (ui/api.py) — те же методы, что дёргает фронт, без
привязки к окну: каждый вызов возвращает {ok, data|error}. Ввод читаем построчно
из stdin — это же делает меню тестируемым: в тестах подсовывается io.StringIO
со сценарием команд и поддельный Api вместо настоящего.
"""

from modules.i18n import t as _tr

import ctypes
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def enable_ansi() -> None:
    """Включает ENABLE_VIRTUAL_TERMINAL_PROCESSING для текущей консоли. Без
    этого старый conhost без Windows Terminal печатает "\\x1b[32m" текстом
    вместо цвета. Тихо ничего не делает вне Windows или без реальной консоли
    (перенаправленный вывод, тесты) — цвет тут не критичен для работы меню."""
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _c(text, color: str) -> str:
    return f"{color}{text}{RESET}"


def _tag(ok: bool, on=None, off=None) -> str:
    on = on if on is not None else _tr('tui.app.running')
    off = off if off is not None else _tr('tui.app.stopped')
    return _c(on, GREEN) if ok else _c(off, RED)


class Quit(Exception):
    """Поднимается при явном выходе из меню и при EOF на stdin (Ctrl+D/конец
    сценария ввода) — оба случая должны гасить процессы так же, как закрытие окна."""


class Menu:
    """Тонкая обёртка над вводом/выводом: печать, чтение строки, устойчивый выбор
    пункта меню (мусор — переспросить, а не упасть)."""

    def __init__(self, api, stdin, out):
        self.api = api
        self.stdin = stdin
        self.out = out

    def print(self, *lines) -> None:
        for line in lines:
            self.out.write(str(line) + "\n")
        self.out.flush()

    def prompt(self, text: str = "> ") -> str:
        self.out.write(text)
        self.out.flush()
        line = self.stdin.readline()
        if line == "":  # EOF — поток ввода кончился (реальный Ctrl+D или сценарий теста)
            raise Quit()
        return line.strip()

    def choice(self, options, prompt: str = _tr('tui.app.choice')) -> str:
        while True:
            raw = self.prompt(prompt)
            if raw in options:
                return raw
            self.print(_c(_tr('tui.app.unknown_item', p0=f'{raw!r}'), YELLOW))

    def run(self, fn, *args, ok_msg: str | None = None):
        """Зовёт метод Api, печатает ошибку или (по желанию) сообщение об успехе."""
        res = fn(*args)
        if not res.get("ok"):
            self.print(_c(_tr('tui.app.error', p0=res.get('error')), RED))
        elif ok_msg:
            self.print(_c(ok_msg, GREEN))
        return res


# --- обзор состояния всех модулей ----------------------------------------------

def _overview(m: Menu) -> None:
    m.print(_c(_tr('tui.app.status'), BOLD))

    w = m.api.winws_state()
    if w["ok"]:
        d = w["data"]
        extra = _tr('tui.app.strategy', p0=d['current']) if d.get("current") else ""
        m.print(f"winws (zapret2):  {_tag(d['running'])}{extra}")
    else:
        m.print(_tr('tui.app.winws_zapret2', p0=_c(_tr('tui.app.error_159') + str(w['error']), RED)))

    p = m.api.proxy_state()
    if p["ok"]:
        d = p["data"]
        m.print(_tr('tui.app.proxy', p0=d.get('mode', 'pac'), p1=_tag(d['running'])))
    else:
        m.print(_tr('tui.app.proxy_95', p0=_c(_tr('tui.app.error_160') + str(p['error']), RED)))

    t = m.api.tg_state()
    if t["ok"]:
        m.print(_tr('tui.app.telegram_proxy_96', p0=_tag(t['data']['running'])))
    else:
        m.print(_tr('tui.app.telegram_proxy_97', p0=_c(_tr('tui.app.error_161') + str(t['error']), RED)))

    h = m.api.hosts_state()
    if h["ok"]:
        d = h["data"]
        state = _tr('tui.app.enabled') if d["enabled"] else _tr('tui.app.disabled')
        m.print(_tr('tui.app.hosts_entries', p0=_tag(d['applied'] and d['enabled']), p1=state, p2=d['count']))
    else:
        m.print(_tr('tui.app.hosts', p0=_c(_tr('tui.app.error_162') + str(h['error']), RED)))

    info = m.api.app_info()
    if info["ok"] and info["data"].get("service_running"):
        m.print(_c(_tr('tui.app.the_chimera_service_is_running_it_manages_the_pr'), YELLOW))
    m.print("")


# --- winws (zapret2) ------------------------------------------------------------

def _pick_strategy(m: Menu, strategies: list[dict]) -> None:
    q = m.prompt(_tr('tui.app.search_by_substring_enter_to_show_all')).strip().lower()
    matches = [s for s in strategies if q in s.get("id", "").lower() or q in s.get("name", "").lower()]
    if not matches:
        m.print(_c(_tr('tui.app.nothing_found'), YELLOW))
        return
    for i, s in enumerate(matches, 1):
        m.print(f"{i}) {s['id']} — {s.get('desc') or s.get('name')}")
    raw = m.prompt(_tr('tui.app.strategy_number_enter_to_cancel'))
    if not raw:
        return
    try:
        sid = matches[int(raw) - 1]["id"]
    except (ValueError, IndexError):
        m.print(_c(_tr('tui.app.invalid_number'), YELLOW))
        return
    m.run(m.api.winws_start, sid, ok_msg=_tr('tui.app.strategy_started', p0=sid))


def _winws_menu(m: Menu) -> None:
    while True:
        st = m.api.winws_state()
        if not st["ok"]:
            m.print(_c(_tr('tui.app.error', p0=st['error']), RED))
            return
        d = st["data"]
        m.print(_c("=== winws (zapret2) ===", BOLD))
        extra = _tr('tui.app.strategy', p0=d['current']) if d.get("current") else ""
        m.print(_tr('tui.app.status_104', p0=_tag(d['running']), p1=extra))
        m.print(_tr('tui.app.1_start_a_strategy_search_by_substring'))
        m.print(_tr('tui.app.2_stop'))
        m.print(_tr('tui.app.3_log_tail'))
        m.print(_tr('tui.app.0_back'))
        c = m.choice({"0", "1", "2", "3"})
        if c == "0":
            return
        if c == "1":
            _pick_strategy(m, d["strategies"])
        elif c == "2":
            m.run(m.api.winws_stop, ok_msg=_tr('tui.app.stopped_151'))
        elif c == "3":
            _tail_log(m, m.api.winws_log)


# --- прокси (sing-box) -----------------------------------------------------------

def _proxy_menu(m: Menu) -> None:
    while True:
        st = m.api.proxy_state()
        if not st["ok"]:
            m.print(_c(_tr('tui.app.error', p0=st['error']), RED))
            return
        d = st["data"]
        m.print(_c(_tr('tui.app.proxy_sing_box_129'), BOLD))
        m.print(_tr('tui.app.status_mode', p0=_tag(d['running']), p1=d.get('mode', 'pac')))
        m.print(_tr('tui.app.1_start'))
        m.print(_tr('tui.app.2_stop'))
        m.print(_tr('tui.app.3_switch_pac_tun_mode'))
        m.print(_tr('tui.app.4_log_tail'))
        m.print(_tr('tui.app.0_back'))
        c = m.choice({"0", "1", "2", "3", "4"})
        if c == "0":
            return
        if c == "1":
            m.run(m.api.proxy_start, ok_msg=_tr('tui.app.started'))
        elif c == "2":
            m.run(m.api.proxy_stop, ok_msg=_tr('tui.app.stopped_152'))
        elif c == "3":
            new_mode = "tun" if d.get("mode", "pac") == "pac" else "pac"
            m.run(m.api.proxy_set_mode, new_mode, ok_msg=_tr('tui.app.mode', p0=new_mode))
        elif c == "4":
            _tail_log(m, m.api.proxy_log)


# --- telegram-прокси --------------------------------------------------------------

def _tg_menu(m: Menu) -> None:
    while True:
        st = m.api.tg_state()
        if not st["ok"]:
            m.print(_c(_tr('tui.app.error', p0=st['error']), RED))
            return
        d = st["data"]
        m.print(_c(_tr('tui.app.telegram_proxy_130'), BOLD))
        m.print(_tr('tui.app.status_115', p0=_tag(d['running'])))
        if d.get("link"):
            m.print(_tr('tui.app.link', p0=d['link']))
        m.print(_tr('tui.app.1_start'))
        m.print(_tr('tui.app.2_stop'))
        m.print(_tr('tui.app.3_log_tail'))
        m.print('4) ' + _tr('tui.tg.h2.off' if d.get('cfproxy_h2_media', True) else 'tui.tg.h2.on'))
        m.print(_tr('tui.app.0_back'))
        c = m.choice({"0", "1", "2", "3", "4"})
        if c == "0":
            return
        if c == "1":
            m.run(m.api.tg_start, ok_msg=_tr('tui.app.started'))
        elif c == "2":
            m.run(m.api.tg_stop, ok_msg=_tr('tui.app.stopped_153'))
        elif c == "3":
            _tail_log(m, m.api.tg_log)
        elif c == "4":
            m.run(m.api.tg_set_advanced, {'cfproxy_h2_media': not d.get('cfproxy_h2_media', True)},
                  ok_msg=_tr('tui.app.done'))


# --- hosts --------------------------------------------------------------------

def _hosts_menu(m: Menu) -> None:
    while True:
        st = m.api.hosts_state()
        if not st["ok"]:
            m.print(_c(_tr('tui.app.error', p0=st['error']), RED))
            return
        d = st["data"]
        m.print(_c("=== Hosts ===", BOLD))
        m.print(_tr('tui.app.hosts_applied_entries',
            p0=_tag(d['enabled'], _tr('tui.app.enabled_154'), _tr('tui.app.disabled_155')),
            p1=_tag(d['applied'], _tr('tui.app.yes'), _tr('tui.app.no')),
            p2=d['count'],
        ))
        m.print(_tr('tui.app.1_disable') if d["enabled"] else _tr('tui.app.1_enable'))
        m.print(_tr('tui.app.0_back'))
        c = m.choice({"0", "1"})
        if c == "0":
            return
        m.run(m.api.hosts_set_enabled, not d["enabled"], ok_msg=_tr('tui.app.done'))


# --- dns ------------------------------------------------------------------------

def _dns_provider_menu(m: Menu, adapter: dict, providers: list[dict]) -> None:
    m.print(_c(_tr('tui.app.adapter', p0=adapter['name']), BOLD))
    for i, p in enumerate(providers, 1):
        m.print(f"{i}) {p['name']}")
    m.print(_tr('tui.app.0_reset_to_dhcp'))
    raw = m.prompt(_tr('tui.app.provider_number_enter_to_cancel'))
    if raw == "":
        return
    if raw == "0":
        m.run(m.api.dns_reset, adapter["index"], ok_msg=_tr('tui.app.dns_reset_to_dhcp'))
        return
    try:
        provider = providers[int(raw) - 1]
    except (ValueError, IndexError):
        m.print(_c(_tr('tui.app.invalid_number'), YELLOW))
        return
    m.run(m.api.dns_set, adapter["index"], provider["id"], ok_msg=_tr('tui.app.adapter_dns', p0=provider['name']))


def _dns_menu(m: Menu) -> None:
    while True:
        st = m.api.dns_state()
        if not st["ok"]:
            m.print(_c(_tr('tui.app.error', p0=st['error']), RED))
            return
        d = st["data"]
        m.print(_c("=== DNS ===", BOLD))
        adapters = d["adapters"]
        for i, a in enumerate(adapters, 1):
            dns = ", ".join(a.get("dns") or []) or "—"
            m.print(f"{i}) {a['name']} [{a.get('status')}] DNS: {dns}")
        m.print(_tr('tui.app.0_back'))
        raw = m.prompt(_tr('tui.app.adapter_number_0_to_go_back'))
        if raw == "0" or raw == "":
            return
        try:
            adapter = adapters[int(raw) - 1]
        except (ValueError, IndexError):
            m.print(_c(_tr('tui.app.invalid_number'), YELLOW))
            continue
        _dns_provider_menu(m, adapter, d["providers"])


# --- логи -------------------------------------------------------------------------

def _tail_log(m: Menu, log_fn, lines: int = 40) -> None:
    res = log_fn(0)
    if not res["ok"]:
        m.print(_c(_tr('tui.app.error', p0=res['error']), RED))
        return
    text = res["data"].get("data", "")
    tail = text.splitlines()[-lines:] if text else []
    m.print(_c(_tr('tui.app.log_tail'), BOLD))
    if not tail:
        m.print(_c(_tr('tui.app.empty'), YELLOW))
    for line in tail:
        m.print(line)
    m.print(_c("------------------", BOLD))


# --- главное меню -----------------------------------------------------------------

MAIN_ITEMS = {
    "1": ("winws (zapret2)", _winws_menu),
    "2": (_tr('tui.app.proxy_sing_box'), _proxy_menu),
    "3": (_tr('tui.app.telegram_proxy'), _tg_menu),
    "4": ("Hosts", _hosts_menu),
    "5": ("DNS", _dns_menu),
    "0": (_tr('tui.app.quit'), None),
}


def _main_loop(m: Menu) -> None:
    while True:
        _overview(m)
        m.print(_c("=== CHIMERA — TUI ===", BOLD))
        for key, (label, _fn) in MAIN_ITEMS.items():
            m.print(f"{key}) {label}")
        c = m.choice(set(MAIN_ITEMS))
        if c == "0":
            return
        MAIN_ITEMS[c][1](m)


def run(api=None, stdin=None, stdout=None) -> int:
    """Точка входа TUI-режима. api=None — поднимает настоящий ui.api.Api (реальные
    модули); в тестах сюда подставляют поддельный объект с теми же методами.
    При выходе (пункт меню, EOF на stdin или Ctrl+C) всегда зовём api.shutdown() —
    так же, как это делает окно при закрытии."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    enable_ansi()
    if api is None:
        from ui.api import Api
        api = Api()
    m = Menu(api, stdin, stdout)
    try:
        _main_loop(m)
    except (Quit, KeyboardInterrupt):
        m.print(_c(_tr('tui.app.exiting'), CYAN))
    finally:
        try:
            api.shutdown()
        except Exception:
            pass
    return 0
