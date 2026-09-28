"""Диагностика: почему обход может не работать.

Две части, чтобы оценка проверялась тестами без системы:
  • gather(api) — собирает факты с живой системы, только чтение, без побочных эффектов;
    любую часть, которую не удалось получить, отдаёт как None;
  • evaluate(data) — чистая функция: факты -> список проверок
    {id, title, status ok|warn|fail, message, hint}.

Отчёт для issue (to_markdown) проходит через mask(): ссылки прокси и секреты
Telegram-прокси в него не попадают, даже если случайно окажутся в тексте проверки.
"""

import platform
import re
import socket
import time

# ссылки прокси (vless://…, trojan://… и т. п.) и секрет в ссылке tg://proxy
_LINK_RE = re.compile(r"\b(vless|vmess|trojan|ss|ssr|hysteria2?|tuic|socks5?|wireguard)://[^\s`'\"<>]+", re.I)
_SECRET_RE = re.compile(r"(secret=)[0-9a-zA-Z]+", re.I)


def mask(text) -> str:
    text = _LINK_RE.sub(lambda m: f"{m.group(1)}://***", str(text))
    return _SECRET_RE.sub(r"\1***", text)


def _check(cid, title, status, message, hint=""):
    return {"id": cid, "title": title, "status": status, "message": mask(message), "hint": mask(hint)}


# --- оценка фактов ---------------------------------------------------------------------

def _missing(cid, title, what):
    return _check(cid, title, "warn", f"Не удалось получить: {what}", "Повторите диагностику или перезапустите Chimera.")


def evaluate(data: dict) -> dict:
    checks = []
    add = checks.append
    winws, proxy, tg = data.get("winws"), data.get("proxy"), data.get("tg")

    # права
    if data.get("admin") is None:
        add(_missing("admin", "Права администратора", "проверка прав"))
    elif data["admin"]:
        add(_check("admin", "Права администратора", "ok", "Chimera работает с правами администратора."))
    else:
        add(_check("admin", "Права администратора", "warn", "Chimera работает без прав администратора.",
                   "Запустите Chimera от имени администратора: без этого не работают обход DPI, "
                   "подмена hosts, смена DNS и режим TUN у прокси."))

    # бандл zapret и драйвер WinDivert
    if data.get("winws_exe") is False:
        add(_check("zapret_bundle", "Бандл zapret (winws2)", "fail", "winws2.exe не найден.",
                   "Переустановите Chimera из релиза или выполните `python tools/fetch_bins.py`."))
    elif data.get("winws_exe"):
        add(_check("zapret_bundle", "Бандл zapret (winws2)", "ok", "winws2.exe на месте."))

    if winws is None:
        add(_missing("windivert", "Драйвер WinDivert", "состояние обхода DPI"))
    else:
        status = winws.get("windivert")
        if winws.get("running") and status != "RUNNING":
            add(_check("windivert", "Драйвер WinDivert", "fail",
                       "winws2 запущен, но служба WinDivert не работает.",
                       "Остановите обход и запустите заново; если не помогает, проверьте антивирус и "
                       "включённую защиту ядра (Secure Boot / целостность памяти): они блокируют драйвер."))
        elif status == "RUNNING":
            add(_check("windivert", "Драйвер WinDivert", "ok", "Служба WinDivert работает."))
        elif status == "STOPPED":
            add(_check("windivert", "Драйвер WinDivert", "ok", "Служба установлена и остановлена: обход выключен."))
        else:
            add(_check("windivert", "Драйвер WinDivert", "ok",
                       "Служба ещё не установлена: она появится при первом запуске стратегии."))

    # чужие процессы
    if winws is not None:
        if winws.get("external"):
            add(_check("foreign_winws", "Чужой winws2", "warn",
                       "Работает winws2, запущенный не этой Chimera (прошлой сессией или другой программой).",
                       "Остановите его на вкладке «Стратегии» или кнопкой «Выключить всё», иначе новая "
                       "стратегия не поднимется."))
        else:
            add(_check("foreign_winws", "Чужой winws2", "ok", "Посторонних процессов winws2 нет."))
    if proxy is not None:
        if proxy.get("external"):
            add(_check("foreign_singbox", "Чужой sing-box", "warn",
                       "Работает sing-box, запущенный не этой Chimera.",
                       "Остановите его на вкладке «Прокси» или кнопкой «Выключить всё»."))
        else:
            add(_check("foreign_singbox", "Чужой sing-box", "ok", "Посторонних процессов sing-box нет."))

    # порты
    ports = data.get("ports") or {}
    for key, label, mod, port in (
            ("port_proxy", "Порт прокси", proxy, (proxy or {}).get("socks_port")),
            ("port_tg", "Порт Telegram-прокси", tg, (tg or {}).get("port"))):
        if mod is None or port is None:
            continue
        if mod.get("running"):
            add(_check(key, label, "ok", f"Порт {port} занят нашим модулем."))
        elif ports.get(key.replace("port_", "")):
            add(_check(key, label, "fail", f"Порт {port} занят другим приложением.",
                       "Закройте это приложение или поменяйте порт в настройках модуля."))
        else:
            add(_check(key, label, "ok", f"Порт {port} свободен."))

    # ядро sing-box
    if proxy is not None:
        core = proxy.get("core") or {}
        if core.get("present"):
            add(_check("singbox_core", "Ядро sing-box", "ok", f"Установлено, версия {core.get('version') or '?'}."))
        else:
            add(_check("singbox_core", "Ядро sing-box", "warn", "Не установлено.",
                       "Нажмите «Скачать sing-box» на вкладке «Прокси», если он вам нужен."))

    # версии компонентов
    versions = data.get("versions")
    if versions is None:
        add(_missing("versions", "Версии компонентов", "версии источников"))
    else:
        text = ", ".join(f"{v.get('name')} {v.get('current')}" for v in versions if v.get("current"))
        add(_check("versions", "Версии компонентов", "ok", text or "Версии неизвестны."))

    # системный прокси / PAC
    sp = data.get("system_proxy")
    if sp is None:
        add(_missing("system_proxy", "Системный прокси", "настройки прокси Windows"))
    else:
        ours = sp.get("autoconfig") and sp.get("autoconfig") == sp.get("our_pac")
        proxy_running = bool((proxy or {}).get("running"))
        if ours and not proxy_running:
            add(_check("system_proxy", "Системный прокси", "warn",
                       "В системе остался PAC Chimera, а прокси не запущен: сайты из списков не откроются.",
                       "Нажмите «Выключить всё» на странице «Обзор» — PAC будет снят."))
        elif sp.get("autoconfig") and not ours:
            add(_check("system_proxy", "Системный прокси", "warn",
                       f"В системе задан чужой PAC: {sp['autoconfig']}",
                       "Он может конфликтовать с прокси Chimera в режиме PAC."))
        elif sp.get("enabled") and sp.get("server"):
            add(_check("system_proxy", "Системный прокси", "warn",
                       f"Включён системный прокси {sp['server']}.",
                       "Он может конфликтовать с прокси Chimera; отключите его, если не он вам нужен."))
        else:
            add(_check("system_proxy", "Системный прокси", "ok", "Системный прокси не мешает."))

    # служба
    svc = data.get("service")
    if svc is not None:
        if svc.get("running"):
            msg = "Фоновая служба Chimera работает: она владеет модулями, окно только показывает их состояние."
        elif svc.get("installed"):
            msg = "Фоновая служба установлена, сейчас не запущена."
        else:
            msg = "Фоновая служба не установлена."
        add(_check("service", "Фоновая служба", "ok", msg))

    add(_check("app", "Программа и система", "ok",
               f"Chimera {data.get('app_version') or '?'}, {data.get('os') or 'ОС неизвестна'}."))

    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "fail")}
    return {"checks": checks, "summary": summary, "generated_at": data.get("generated_at") or int(time.time())}


# --- отчёт для issue -----------------------------------------------------------------

_ICONS = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def to_markdown(result: dict) -> str:
    s = result["summary"]
    lines = ["### Диагностика Chimera", "",
             f"Итог: ✅ {s['ok']}  ⚠️ {s['warn']}  ❌ {s['fail']}", ""]
    for c in result["checks"]:
        lines.append(f"- {_ICONS.get(c['status'], '•')} **{c['title']}**: {c['message']}")
        if c["status"] != "ok" and c.get("hint"):
            lines.append(f"  - Подсказка: {c['hint']}")
    return mask("\n".join(lines)) + "\n"


# --- сбор фактов (только чтение) ---------------------------------------------------------

def _try(fn):
    try:
        return fn()
    except Exception:
        return None


def _port_in_use(host: str, port: int) -> bool:
    host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((host, int(port)), timeout=0.4):
            return True
    except OSError:
        return False


def _read_system_proxy(our_pac: str) -> dict:
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    out = {"autoconfig": None, "our_pac": our_pac, "enabled": False, "server": None}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
        for name, field in (("AutoConfigURL", "autoconfig"), ("ProxyEnable", "enabled"), ("ProxyServer", "server")):
            try:
                value, _ = winreg.QueryValueEx(k, name)
            except OSError:
                continue
            out[field] = bool(value) if field == "enabled" else (str(value) or None)
    return out


def gather(api) -> dict:
    """Факты с живой системы. api — экземпляр ui.api.Api (его менеджеры уже подняты)."""
    from . import service, upstream
    from .hosts.manager import is_admin
    from .version import VERSION
    from .winws.manager import WINWS_EXE

    winws = _try(api.winws.state)
    proxy = _try(api.proxy.state)
    tg = _try(api.tg.state)
    ports = {}
    if proxy and proxy.get("socks_port") is not None:
        ports["proxy"] = _port_in_use("127.0.0.1", proxy["socks_port"])
    if tg and tg.get("port") is not None:
        ports["tg"] = _port_in_use(tg.get("host") or "127.0.0.1", tg["port"])
    return {
        "admin": _try(is_admin),
        "app_version": VERSION,
        "os": platform.platform(),
        "winws_exe": _try(WINWS_EXE.exists),
        "winws": winws, "proxy": proxy, "tg": tg, "ports": ports,
        "versions": _try(upstream.versions),
        "system_proxy": _try(lambda: _read_system_proxy(api.proxy._pac_url())),
        "service": _try(service.status),
    }


def run(api) -> dict:
    return evaluate(gather(api))
