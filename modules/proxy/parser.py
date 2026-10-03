"""Разбор share-ссылок (vless:// и т.д.) в outbound-конфиг sing-box.

Поддержка: vless, trojan, shadowsocks (ss), vmess. Возвращаем словарь:
  {"outbound": {...sing-box outbound...}, "label", "protocol", "server", "security"}
Бросаем ValueError на нечитаемой/неподдержанной ссылке.
"""

from modules.errors import ChimeraValueError

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit


def _qs(query: str) -> dict:
    """query -> плоский dict (берём первое значение каждого ключа)."""
    return {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}


def _b64(s: str) -> bytes:
    s = "".join(s.split()).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s, validate=True)


def _integer(value) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.isascii() and value.isdecimal():
            try:
                return int(value)
            except ValueError:
                pass
    return None


def _port(value) -> int:
    port = _integer(value)
    if port is None or not 1 <= port <= 65535:
        raise ChimeraValueError('err.proxy.parser.invalid_port')
    return port


def _tls_block(q: dict, default_sni: str) -> dict | None:
    sec = (q.get("security") or "").lower()
    if sec in ("", "none"):
        return None
    sni = q.get("sni") or q.get("peer") or q.get("host") or default_sni
    tls = {"enabled": True, "server_name": sni}
    if q.get("fp"):
        tls["utls"] = {"enabled": True, "fingerprint": q["fp"]}
    if q.get("alpn"):
        tls["alpn"] = [a for a in q["alpn"].split(",") if a]
    if q.get("allowInsecure") in ("1", "true") or q.get("insecure") in ("1", "true"):
        tls["insecure"] = True
    if sec == "reality":
        tls["reality"] = {
            "enabled": True,
            "public_key": q.get("pbk", ""),
            "short_id": q.get("sid", ""),
        }
        tls.setdefault("utls", {"enabled": True, "fingerprint": q.get("fp") or "chrome"})
    return tls


def _transport(q: dict) -> dict | None:
    net = (q.get("type") or q.get("net") or "tcp").lower()
    if net in ("tcp", "raw", ""):
        return None
    if net == "ws":
        t = {"type": "ws", "path": q.get("path", "/")}
        if q.get("host"):
            t["headers"] = {"Host": q["host"]}
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": q.get("serviceName") or q.get("path", "")}
    if net in ("http", "h2"):
        t = {"type": "http"}
        if q.get("host"):
            t["host"] = [h for h in q["host"].split(",") if h]
        if q.get("path"):
            t["path"] = q["path"]
        return t
    if net == "httpupgrade":
        t = {"type": "httpupgrade", "path": q.get("path", "/")}
        if q.get("host"):
            t["host"] = q["host"]
        return t
    return None  # неизвестный транспорт — пусть будет tcp


def _parse_vless(u) -> dict:
    q = _qs(u.query)
    host, port = u.hostname, u.port
    if not host or not port:
        raise ChimeraValueError('err.proxy.parser.vless_missing_host_port')
    ob = {"type": "vless", "server": host, "server_port": int(port),
          "uuid": unquote(u.username or "")}
    if q.get("flow"):
        ob["flow"] = q["flow"]
    tls = _tls_block(q, host)
    if tls:
        ob["tls"] = tls
    tr = _transport(q)
    if tr:
        ob["transport"] = tr
    return ob


def _parse_trojan(u) -> dict:
    q = _qs(u.query)
    host, port = u.hostname, u.port
    if not host or not port:
        raise ChimeraValueError('err.proxy.parser.trojan_missing_host_port')
    ob = {"type": "trojan", "server": host, "server_port": int(port),
          "password": unquote(u.username or "")}
    # у trojan TLS по умолчанию включён, даже если security не указан
    tls = _tls_block(q, host) or {"enabled": True, "server_name": q.get("sni") or host}
    ob["tls"] = tls
    tr = _transport(q)
    if tr:
        ob["transport"] = tr
    return ob


def _parse_ss(u, raw: str) -> dict:
    host, port = u.hostname, u.port
    if host and port and u.username:
        credentials = _b64(unquote(u.username)).decode("utf-8")
    else:
        body = raw[len("ss://"):].split("#", 1)[0].split("?", 1)[0]
        decoded = _b64(body).decode("utf-8")
        credentials, separator, authority = decoded.rpartition("@")
        if not separator:
            raise ChimeraValueError('err.proxy.parser.ss_could_not_parse_host_port')
        endpoint = urlsplit("//" + authority)
        host, port = endpoint.hostname, endpoint.port
        if endpoint.username is not None or endpoint.path or endpoint.query or endpoint.fragment:
            raise ChimeraValueError('err.proxy.parser.ss_could_not_parse_host_port')
    method, separator, password = credentials.partition(":")
    if not host or not port or not method or not separator:
        raise ChimeraValueError('err.proxy.parser.ss_could_not_parse_host_port')
    return {"type": "shadowsocks", "server": host, "server_port": _port(port),
            "method": method, "password": password}


def _parse_vmess(raw: str) -> tuple[dict, str]:
    """-> (outbound, имя профиля из поля ps: у vmess-ссылок оно внутри JSON, а не в #фрагменте)."""
    cfg = json.loads(_b64(raw[len("vmess://"):]).decode("utf-8"))
    if not isinstance(cfg, dict):
        raise ChimeraValueError('err.proxy.parser.invalid_vmess_configuration')
    for key in ("add", "id", "net", "path", "host", "tls", "sni", "ps"):
        if key in cfg and not isinstance(cfg[key], str):
            raise ChimeraValueError('err.proxy.parser.invalid_vmess_configuration')
    host, port = cfg.get("add"), cfg.get("port")
    if not host or not port:
        raise ChimeraValueError('err.proxy.parser.vmess_missing_add_port')
    raw_aid = cfg.get("aid")
    alter_id = _integer(0 if raw_aid is None or raw_aid == "" else raw_aid)
    if alter_id is None or alter_id < 0:
        raise ChimeraValueError('err.proxy.parser.invalid_vmess_configuration')
    ob = {"type": "vmess", "server": host, "server_port": _port(port),
          "uuid": cfg.get("id", ""),
          "alter_id": alter_id,
          "security": "auto"}
    q = {"type": cfg.get("net", "tcp"), "host": cfg.get("host", ""),
         "path": cfg.get("path", ""), "serviceName": cfg.get("path", "")}
    if str(cfg.get("tls", "")).lower() in ("tls", "reality"):
        q["security"] = cfg["tls"]
        q["sni"] = cfg.get("sni") or cfg.get("host") or host
        tls = _tls_block(q, host)
        if tls:
            ob["tls"] = tls
    tr = _transport(q)
    if tr:
        ob["transport"] = tr
    return ob, str(cfg.get("ps") or "").strip()


def _hostport(host: str, port) -> str:
    # IPv6 — в скобках, иначе порт сливается с последней группой адреса
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


_PARSERS = {"vless": _parse_vless, "trojan": _parse_trojan}


def parse_link(raw: str) -> dict:
    if raw is not None and not isinstance(raw, str):
        raise ChimeraValueError('err.proxy.parser.this_does_not_look_like_a_link_missing_scheme')
    raw = (raw or "").strip()
    scheme = raw.split("://", 1)[0].lower() if "://" in raw else ""
    if not scheme:
        raise ChimeraValueError('err.proxy.parser.this_does_not_look_like_a_link_missing_scheme')
    u = urlsplit(raw)
    name = ""
    if scheme in _PARSERS:
        ob = _PARSERS[scheme](u)
    elif scheme == "ss":
        ob = _parse_ss(u, raw)
    elif scheme == "vmess":
        ob, name = _parse_vmess(raw)
    else:
        raise ChimeraValueError('err.proxy.parser.protocol_is_not_supported_use_vless_trojan_ss_vm', p0=scheme)
    server = _hostport(ob["server"], ob["server_port"])
    label = unquote(u.fragment) if u.fragment else (name or server)
    sec = "reality" if ob.get("tls", {}).get("reality") else (
        "tls" if ob.get("tls", {}).get("enabled") else "none")
    return {
        "outbound": ob,
        "label": label,
        "protocol": ob["type"],
        "server": server,
        "security": sec,
    }
