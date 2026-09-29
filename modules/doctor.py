"""Диагностика: почему обход может не работать.

Две части, чтобы оценка проверялась тестами без системы:
  • gather(api) — собирает факты с живой системы, только чтение, без побочных эффектов;
    любую часть, которую не удалось получить, отдаёт как None;
  • evaluate(data) — чистая функция: факты -> список проверок
    {id, title, status ok|warn|fail, message, hint, code, params}.

Тексты проверок лежат в каталоге: заголовок — `doctor.<id>.title`, сообщение и подсказка —
`<code>.message` и `<code>.hint` (code вроде `doctor.admin.warn` и params лежат в самой
проверке). Окно может собрать текст на своём языке по ним; title, message и hint уже
приходят на языке программы.

Отчёт для issue (to_markdown) проходит через mask(): ссылки прокси и секреты
Telegram-прокси в него не попадают, даже если случайно окажутся в тексте проверки.
"""

import platform
import re
import socket
import time

from modules.i18n import has, t

# ссылки прокси (vless://…, trojan://… и т. п.) и секрет в ссылке tg://proxy
_LINK_RE = re.compile(r"\b(vless|vmess|trojan|ss|ssr|hysteria2?|tuic|socks5?|wireguard)://[^\s`'\"<>]+", re.I)
_SECRET_RE = re.compile(r"(secret=)[0-9a-zA-Z]+", re.I)

# id проверок; у каждой в каталоге есть `doctor.<id>.title`
CHECK_IDS = ("admin", "zapret_bundle", "windivert", "foreign_winws", "foreign_singbox", "port_proxy",
             "port_tg", "singbox_core", "versions", "system_proxy", "service", "app")


def mask(text) -> str:
    text = _LINK_RE.sub(lambda m: f"{m.group(1)}://***", str(text))
    return _SECRET_RE.sub(r"\1***", text)


def _check(cid, status, code, **params):
    """Проверка с готовым текстом на текущем языке. Всё, что попадёт в текст или в параметры,
    проходит через mask()."""
    params = {k: mask(v) if isinstance(v, str) else v for k, v in params.items()}
    hint = t(f"{code}.hint", **params) if has(f"{code}.hint") else ""
    return {"id": cid, "title": t(f"doctor.{cid}.title"), "status": status,
            "message": mask(t(f"{code}.message", **params)), "hint": mask(hint),
            "code": code, "params": params}


# --- оценка фактов ---------------------------------------------------------------------

def evaluate(data: dict) -> dict:
    checks = []
    add = checks.append
    winws, proxy, tg = data.get("winws"), data.get("proxy"), data.get("tg")

    # права
    if data.get("admin") is None:
        add(_check("admin", "warn", "doctor.admin.missing"))
    elif data["admin"]:
        add(_check("admin", "ok", "doctor.admin.ok"))
    else:
        add(_check("admin", "warn", "doctor.admin.warn"))

    # бандл zapret и драйвер WinDivert
    if data.get("winws_exe") is False:
        add(_check("zapret_bundle", "fail", "doctor.zapret_bundle.fail"))
    elif data.get("winws_exe"):
        add(_check("zapret_bundle", "ok", "doctor.zapret_bundle.ok"))

    if winws is None:
        add(_check("windivert", "warn", "doctor.windivert.missing"))
    else:
        status = winws.get("windivert")
        if winws.get("running") and status != "RUNNING":
            add(_check("windivert", "fail", "doctor.windivert.fail"))
        elif status == "RUNNING":
            add(_check("windivert", "ok", "doctor.windivert.running"))
        elif status == "STOPPED":
            add(_check("windivert", "ok", "doctor.windivert.stopped"))
        else:
            add(_check("windivert", "ok", "doctor.windivert.absent"))

    # чужие процессы
    if winws is not None:
        if winws.get("external"):
            add(_check("foreign_winws", "warn", "doctor.foreign_winws.warn"))
        else:
            add(_check("foreign_winws", "ok", "doctor.foreign_winws.ok"))
    if proxy is not None:
        if proxy.get("external"):
            add(_check("foreign_singbox", "warn", "doctor.foreign_singbox.warn"))
        else:
            add(_check("foreign_singbox", "ok", "doctor.foreign_singbox.ok"))

    # порты
    ports = data.get("ports") or {}
    for key, mod, port in (
            ("port_proxy", proxy, (proxy or {}).get("socks_port")),
            ("port_tg", tg, (tg or {}).get("port"))):
        if mod is None or port is None:
            continue
        if mod.get("running"):
            add(_check(key, "ok", "doctor.port.ours", port=port))
        elif ports.get(key.replace("port_", "")):
            add(_check(key, "fail", "doctor.port.busy", port=port))
        else:
            add(_check(key, "ok", "doctor.port.free", port=port))

    # ядро sing-box
    if proxy is not None:
        core = proxy.get("core") or {}
        if core.get("present"):
            add(_check("singbox_core", "ok", "doctor.singbox_core.ok", version=core.get("version") or "?"))
        else:
            add(_check("singbox_core", "warn", "doctor.singbox_core.warn"))

    # версии компонентов
    versions = data.get("versions")
    if versions is None:
        add(_check("versions", "warn", "doctor.versions.missing"))
    else:
        text = ", ".join(f"{v.get('name')} {v.get('current')}" for v in versions if v.get("current"))
        add(_check("versions", "ok", "doctor.versions.list", list=text) if text
            else _check("versions", "ok", "doctor.versions.unknown"))

    # системный прокси / PAC
    sp = data.get("system_proxy")
    if sp is None:
        add(_check("system_proxy", "warn", "doctor.system_proxy.missing"))
    else:
        ours = sp.get("autoconfig") and sp.get("autoconfig") == sp.get("our_pac")
        proxy_running = bool((proxy or {}).get("running"))
        if ours and not proxy_running:
            add(_check("system_proxy", "warn", "doctor.system_proxy.stale_pac"))
        elif sp.get("autoconfig") and not ours:
            add(_check("system_proxy", "warn", "doctor.system_proxy.foreign_pac", pac=sp["autoconfig"]))
        elif sp.get("enabled") and sp.get("server"):
            add(_check("system_proxy", "warn", "doctor.system_proxy.enabled", server=sp["server"]))
        else:
            add(_check("system_proxy", "ok", "doctor.system_proxy.ok"))

    # служба
    svc = data.get("service")
    if svc is not None:
        if svc.get("running"):
            code = "doctor.service.running"
        elif svc.get("installed"):
            code = "doctor.service.installed"
        else:
            code = "doctor.service.absent"
        add(_check("service", "ok", code))

    add(_check("app", "ok", "doctor.app.ok", version=data.get("app_version") or "?",
               os=data.get("os") or t("doctor.app.unknown_os")))

    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "fail")}
    return {"checks": checks, "summary": summary, "generated_at": data.get("generated_at") or int(time.time())}


# --- отчёт для issue -----------------------------------------------------------------

_ICONS = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def to_markdown(result: dict) -> str:
    s = result["summary"]
    lines = [t("doctor.report.title"), "", t("doctor.report.total", ok=s["ok"], warn=s["warn"], fail=s["fail"]), ""]
    for c in result["checks"]:
        lines.append(f"- {_ICONS.get(c['status'], '•')} **{c['title']}**: {c['message']}")
        if c["status"] != "ok" and c.get("hint"):
            lines.append("  - " + t("doctor.report.hint", hint=c["hint"]))
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
