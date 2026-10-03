"""Разбор share-ссылок (vless:// и т.д.) в outbound-конфиг sing-box.

Поддержка: vless, trojan, shadowsocks (ss), vmess, hysteria2 (hy2), hysteria, tuic, anytls,
socks (socks4/4a/5/5h), http/https. Возвращаем словарь:
  {"outbound": {...sing-box outbound...}, "label", "protocol", "server", "security"}
Бросаем ValueError на нечитаемой/неподдержанной ссылке.
"""

from modules.errors import ChimeraValueError

import base64
import json
import re
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
    if net == "quic":
        return {"type": "quic"}
    # xhttp/splithttp/kcp — транспорты Xray: молча подменить их на tcp значит получить
    # соединение, которое не работает без объяснения причин
    raise ChimeraValueError('err.proxy.parser.unsupported_transport', p0=net)


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
    ob = {"type": "shadowsocks", "server": host, "server_port": _port(port),
          "method": method, "password": password}
    # SIP002: plugin=obfs-local;obfs=http;obfs-host=… — у sing-box те же имена плагинов
    plugin, _, options = _qs(u.query).get("plugin", "").partition(";")
    if plugin:
        plugin = {"simple-obfs": "obfs-local"}.get(plugin, plugin)
        if plugin not in ("obfs-local", "v2ray-plugin"):
            raise ChimeraValueError('err.proxy.parser.unsupported_ss_plugin', p0=plugin)
        ob["plugin"] = plugin
        if options:
            ob["plugin_opts"] = options
    return ob


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


def _endpoint(u, default_port: int | None, *, ranges=False) -> tuple[str, str, str, int, list[str]]:
    """-> (логин, пароль, хост, порт, диапазоны портов). Разбираем netloc сами: urlsplit падает
    на портах вида «443,20000-30000», которые hysteria2 использует для смены портов."""
    userinfo, _, hostport = u.netloc.rpartition("@")
    user, _, password = userinfo.partition(":")
    if hostport.startswith("["):
        host, _, rest = hostport[1:].partition("]")
        spec = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, spec = hostport.partition(":")
    host = unquote(host)
    if not host:
        raise ChimeraValueError('err.proxy.parser.missing_host')
    if not spec:
        if default_port is None:
            raise ChimeraValueError('err.proxy.parser.invalid_port')
        return unquote(user), unquote(password), host, default_port, []
    first, extra = spec.split(",", 1)[0], spec.split(",")[1:]
    hops = []
    for item in ([first] if "-" in first else []) + extra:
        low, dash, high = item.partition("-")
        if not ranges or (dash and _port(low) > _port(high)):
            raise ChimeraValueError('err.proxy.parser.invalid_port')
        hops.append(f"{_port(low)}:{_port(high or low)}")
    port = _port(first.partition("-")[0])
    return unquote(user), unquote(password), host, port, hops


def _flag(q: dict, *keys) -> bool:
    return any(str(q.get(k, "")).lower() in ("1", "true", "yes") for k in keys)


def _tls(q: dict, host: str, *, alpn=None) -> dict:
    """TLS для протоколов, где он обязателен (hysteria2, tuic, anytls, https-прокси)."""
    tls = {"enabled": True, "server_name": q.get("sni") or q.get("peer") or host}
    if _flag(q, "insecure", "allowInsecure", "allow_insecure", "skip-cert-verify"):
        tls["insecure"] = True
    names = [a for a in (q.get("alpn") or alpn or "").split(",") if a]
    if names:
        tls["alpn"] = names
    if q.get("fp"):
        tls["utls"] = {"enabled": True, "fingerprint": q["fp"]}
    return tls


def _mbps(value, default: int) -> int:
    # «100», «100 mbps», «100Mbps» — у клиентов встречаются все три
    number = _integer(str(value or "").lower().replace("mbps", "").strip()) if value else default
    if number is None or number < 1:
        raise ChimeraValueError('err.proxy.parser.invalid_bandwidth')
    return number


def _parse_hysteria2(u) -> dict:
    q = _qs(u.query)
    user, password, host, port, hops = _endpoint(u, 443, ranges=True)
    auth = f"{user}:{password}" if password else user
    ob = {"type": "hysteria2", "server": host, "server_port": port, "password": q.get("auth") or auth,
          "tls": _tls(q, host)}
    if hops or q.get("mport"):
        ob["server_ports"] = hops or [r.replace("-", ":") for r in q["mport"].split(",") if r]
    if (q.get("obfs") or "").lower() == "salamander":
        ob["obfs"] = {"type": "salamander", "password": q.get("obfs-password", "")}
    elif q.get("obfs") not in (None, "", "none"):
        raise ChimeraValueError('err.proxy.parser.unsupported_obfs', p0=q["obfs"])
    for key, field in (("upmbps", "up_mbps"), ("downmbps", "down_mbps")):
        if q.get(key):
            ob[field] = _mbps(q[key], 0)
    return ob


def _parse_hysteria(u) -> dict:
    q = _qs(u.query)
    _user, _password, host, port, _hops = _endpoint(u, None)
    if (q.get("protocol") or "udp").lower() != "udp":
        raise ChimeraValueError('err.proxy.parser.unsupported_hysteria_protocol', p0=q["protocol"])
    ob = {"type": "hysteria", "server": host, "server_port": port,
          # без скоростей ядро не стартует: берём умеренные значения, как клиенты по умолчанию
          "up_mbps": _mbps(q.get("upmbps") or q.get("up"), 10),
          "down_mbps": _mbps(q.get("downmbps") or q.get("down"), 50),
          "tls": _tls(q, host, alpn="hysteria")}
    if q.get("auth"):
        ob["auth_str"] = q["auth"]
    if q.get("obfsParam") or q.get("obfs-password"):
        ob["obfs"] = q.get("obfsParam") or q["obfs-password"]
    return ob


def _parse_tuic(u) -> dict:
    q = _qs(u.query)
    uuid, password, host, port, _hops = _endpoint(u, None)
    if not uuid:
        raise ChimeraValueError('err.proxy.parser.missing_credentials')
    ob = {"type": "tuic", "server": host, "server_port": port, "uuid": uuid, "password": password,
          "tls": _tls(q, host, alpn="h3")}
    if q.get("congestion_control") or q.get("congestion-control"):
        ob["congestion_control"] = q.get("congestion_control") or q["congestion-control"]
    mode = q.get("udp_relay_mode") or q.get("udp-relay-mode")
    if mode:
        if mode not in ("native", "quic"):
            raise ChimeraValueError('err.proxy.parser.invalid_tuic_relay_mode', p0=mode)
        ob["udp_relay_mode"] = mode
    if _flag(q, "reduce_rtt", "zero_rtt_handshake"):
        ob["zero_rtt_handshake"] = True
    return ob


def _parse_anytls(u) -> dict:
    q = _qs(u.query)
    user, password, host, port, _hops = _endpoint(u, 443)
    if not user:
        raise ChimeraValueError('err.proxy.parser.missing_credentials')
    return {"type": "anytls", "server": host, "server_port": port,
            "password": f"{user}:{password}" if password else user, "tls": _tls(q, host)}


_SOCKS = {"socks": "5", "socks5": "5", "socks5h": "5", "socks4": "4", "socks4a": "4a"}


def _parse_socks(u, scheme: str) -> dict:
    user, password, host, port, _hops = _endpoint(u, 1080)
    ob = {"type": "socks", "server": host, "server_port": port, "version": _SOCKS[scheme]}
    if user:
        if _SOCKS[scheme] != "5" and password:
            raise ChimeraValueError('err.proxy.parser.socks4_no_password')
        ob["username"] = user
    if password:
        ob["password"] = password
    return ob


def _parse_http(u, scheme: str) -> dict:
    q = _qs(u.query)
    user, password, host, port, _hops = _endpoint(u, 443 if scheme == "https" else 80)
    ob = {"type": "http", "server": host, "server_port": port}
    if user:
        ob["username"] = user
    if password:
        ob["password"] = password
    if scheme == "https":
        ob["tls"] = _tls(q, host)
    return ob


def _parse_naive(u, quic: bool) -> dict:
    q = _qs(u.query)
    user, password, host, port, _hops = _endpoint(u, 443)
    ob = {"type": "naive", "server": host, "server_port": port, "tls": _tls(q, host)}
    if user:
        ob["username"] = user
    if password:
        ob["password"] = password
    if quic:
        ob["quic"] = True
    return ob


def _parse_ssh(u) -> dict:
    user, password, host, port, _hops = _endpoint(u, 22)
    ob = {"type": "ssh", "server": host, "server_port": port, "user": user or "root"}
    if password:
        ob["password"] = password
    return ob


def _parse_snell(u) -> dict:
    q = _qs(u.query)
    psk, _password, host, port, _hops = _endpoint(u, None)
    psk = psk or q.get("psk", "")
    if not psk:
        raise ChimeraValueError('err.proxy.parser.missing_credentials')
    version = _integer(q.get("version") or "4")
    if version not in (1, 2, 3, 4):
        raise ChimeraValueError('err.proxy.parser.invalid_snell_version')
    ob = {"type": "snell", "server": host, "server_port": port, "psk": psk, "version": version}
    if q.get("obfs") and q["obfs"] != "none":
        ob["obfs_mode"] = q["obfs"]
        if q.get("obfs-host"):
            ob["obfs_host"] = q["obfs-host"]
    return ob


def _first(q: dict, *keys) -> str:
    return next((q[k] for k in keys if q.get(k)), "")


def _parse_wireguard(u) -> dict:
    """wireguard:// (v2rayN, NekoBox) и wg:// (Hiddify): ключ клиента — в userinfo или в параметре."""
    q = _qs(u.query)
    key, _password, host, port, _hops = _endpoint(u, 51820)
    private_key = key or _first(q, "privatekey", "privateKey", "secretKey", "pk")
    public_key = _first(q, "publickey", "publicKey", "peer_pk", "peer_public_key")
    if not private_key or not public_key:
        raise ChimeraValueError('err.proxy.parser.wireguard_missing_keys')
    addresses = [a for a in _first(q, "address", "ip", "local_address").split(",") if a]
    if not addresses:
        raise ChimeraValueError('err.proxy.parser.wireguard_missing_address')
    # адрес без маски — один хост: /32 для IPv4, /128 для IPv6
    addresses = [a if "/" in a else a + ("/128" if ":" in a else "/32") for a in addresses]
    peer = {"address": host, "port": port, "public_key": public_key, "allowed_ips": ["0.0.0.0/0", "::/0"]}
    psk = _first(q, "presharedkey", "preSharedKey", "pre_shared_key", "psk")
    if psk:
        peer["pre_shared_key"] = psk
    if q.get("reserved"):
        reserved = [_integer(part) for part in q["reserved"].split(",")]
        if len(reserved) != 3 or any(r is None or not 0 <= r <= 255 for r in reserved):
            raise ChimeraValueError('err.proxy.parser.wireguard_invalid_reserved')
        peer["reserved"] = reserved
    ob = {"type": "wireguard", "address": addresses, "private_key": private_key, "peers": [peer]}
    if q.get("mtu"):
        mtu = _integer(q["mtu"])
        if mtu is None or not 576 <= mtu <= 9000:
            raise ChimeraValueError('err.proxy.parser.wireguard_invalid_mtu')
        ob["mtu"] = mtu
    return ob


def _parse_telegram(u) -> dict:
    """tg://socks?server=…&port=… и https://t.me/socks?… — SOCKS5 из ссылки Telegram.
    MTProto (tg://proxy) ядро sing-box не умеет: для него есть свой модуль Telegram."""
    kind = (u.netloc if u.scheme.lower() == "tg" else u.path.strip("/")).lower()
    if kind == "proxy":
        raise ChimeraValueError('err.proxy.parser.mtproto_link')
    if kind != "socks":
        raise ChimeraValueError('err.proxy.parser.protocol_is_not_supported_use_vless_trojan_ss_vm', p0=u.scheme)
    q = _qs(u.query)
    if not q.get("server"):
        raise ChimeraValueError('err.proxy.parser.missing_host')
    ob = {"type": "socks", "server": q["server"], "server_port": _port(q.get("port") or "1080"), "version": "5"}
    if q.get("user"):
        ob["username"] = q["user"]
    if q.get("pass"):
        ob["password"] = q["pass"]
    return ob


_PARSERS = {"vless": _parse_vless, "trojan": _parse_trojan, "hysteria2": _parse_hysteria2, "hy2": _parse_hysteria2,
            "hysteria": _parse_hysteria, "tuic": _parse_tuic, "anytls": _parse_anytls, "ssh": _parse_ssh,
            "snell": _parse_snell, "wireguard": _parse_wireguard, "wg": _parse_wireguard, "tg": _parse_telegram,
            "naive+https": lambda u: _parse_naive(u, False), "naive+quic": lambda u: _parse_naive(u, True)}

# типы, которые в sing-box задаются в endpoints, а не в outbounds
ENDPOINT_TYPES = frozenset({"wireguard", "tailscale"})
# что можно вставить готовым JSON: всё, через что sing-box умеет ходить наружу
JSON_TYPES = frozenset({"socks", "http", "shadowsocks", "vmess", "trojan", "naive", "hysteria", "vless", "shadowtls",
                        "tuic", "hysteria2", "anytls", "tor", "ssh", "snell"}) | ENDPOINT_TYPES
_SCHEMES = sorted([*_PARSERS, "ss", "vmess", "http", "https", *_SOCKS], key=len, reverse=True)
_LINK_RE = re.compile(r"(?<![\w+.-])(" + "|".join(re.escape(s) for s in _SCHEMES) + r")://[^\s\"'<>]+", re.I)
_ANY_SCHEME_RE = re.compile(r"(?<![\w+.-])([a-z][a-z0-9+.-]*)://", re.I)


def _extract(raw) -> str:
    """Ссылка из того, что вставили: сообщение с текстом вокруг, base64-подписка, JSON."""
    if raw is not None and not isinstance(raw, str):
        raise ChimeraValueError('err.proxy.parser.this_does_not_look_like_a_link_missing_scheme')
    text = (raw or "").strip()
    if text.startswith(("{", "[")):
        return text
    match = _LINK_RE.search(text)
    if match and match.start() == 0 and text.count("://") == 1:
        # вся вставка — одна ссылка: берём целиком, base64 vmess/ss бывает разбит переносами
        return text
    if match:
        return match.group(0)
    if text and "://" not in text:
        try:
            decoded = _b64(text).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        if "://" in decoded:
            return _extract(decoded)
    other = _ANY_SCHEME_RE.search(text)
    if other:
        raise ChimeraValueError('err.proxy.parser.protocol_is_not_supported_use_vless_trojan_ss_vm',
                                p0=other.group(1).lower())
    raise ChimeraValueError('err.proxy.parser.this_does_not_look_like_a_link_missing_scheme')


def _from_json(text: str) -> tuple[dict, list[dict], str]:
    """Outbound/endpoint sing-box как есть: одним объектом, списком или целым конфигом.
    -> (основной, то, на что он ссылается через detour, подпись)."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ChimeraValueError('err.proxy.parser.invalid_json') from None
    if isinstance(data, dict) and ("outbounds" in data or "endpoints" in data):
        items = [*(data.get("endpoints") or []), *(data.get("outbounds") or [])]
    elif isinstance(data, list):
        items = data
    else:
        items = [data]
    if not all(isinstance(i, dict) for i in items):
        raise ChimeraValueError('err.proxy.parser.invalid_json')
    by_tag = {i.get("tag"): i for i in items if i.get("tag")}
    # основной — первый прокси, на который не ссылается detour другого (shadowtls под shadowsocks)
    detours = {i.get("detour") for i in items}
    main = next((i for i in items if i.get("type") in JSON_TYPES and i.get("tag") not in detours), None)
    if main is None:
        kinds = sorted({str(i.get("type")) for i in items})
        raise ChimeraValueError('err.proxy.parser.unsupported_json_type', p0=", ".join(kinds) or "—")
    chain, current = [], main
    while current.get("detour"):
        current = by_tag.get(current["detour"])
        if current is None or current in chain or current is main:
            raise ChimeraValueError('err.proxy.parser.invalid_json')
        chain.append(current)
    label = str(main.get("tag") or main["type"])
    return {k: v for k, v in main.items() if k != "tag"}, [dict(c) for c in chain], label


def _server(ob: dict) -> str:
    if ob.get("server") and ob.get("server_port"):
        return _hostport(ob["server"], ob["server_port"])
    peer = (ob.get("peers") or [{}])[0]
    if peer.get("address") and peer.get("port"):
        return _hostport(peer["address"], peer["port"])
    return ob.get("server") or "—"


def parse_link(raw: str) -> dict:
    """-> {"outbound", "chain", "label", "protocol", "server", "security"}; chain — outbound'ы,
    на которые основной ссылается через detour (бывает только во вставленном JSON)."""
    text = _extract(raw)
    chain, name = [], ""
    if text.startswith(("{", "[")):
        ob, chain, name = _from_json(text)
        u = urlsplit("")
    else:
        scheme = text.split("://", 1)[0].lower()
        u = urlsplit(text)
        if scheme in ("http", "https") and (u.hostname or "").lower() in ("t.me", "telegram.me"):
            ob = _parse_telegram(u)
        elif scheme in ("http", "https") and (u.path.strip("/") or u.query):
            # у прокси нет пути: адрес с путём или параметрами — это подписка или просто сайт
            raise ChimeraValueError('err.proxy.parser.looks_like_subscription')
        elif scheme in _PARSERS:
            ob = _PARSERS[scheme](u)
        elif scheme == "ss":
            ob = _parse_ss(u, text)
        elif scheme == "vmess":
            ob, name = _parse_vmess(text)
        elif scheme in _SOCKS:
            ob = _parse_socks(u, scheme)
        else:
            ob = _parse_http(u, scheme)
    server = _server(ob)
    label = unquote(u.fragment) if u.fragment else (name or server)
    tls = ob.get("tls") or {}
    sec = "reality" if tls.get("reality", {}).get("enabled") else ("tls" if tls.get("enabled") else "none")
    return {
        "outbound": ob,
        "chain": chain,
        "label": label,
        "protocol": ob["type"],
        "server": server,
        "security": sec,
    }
