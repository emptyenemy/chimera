"""Список сетевых адаптеров через WinAPI (GetAdaptersAddresses, ctypes) —
без PowerShell. Get-NetAdapter + Get-DnsClientServerAddress + Get-NetIPAddress
на этой машине занимали ~2-2.5 c (поднятие powershell.exe — почти вся цена),
а хаб дёргает dns_state, пока открыта вкладка DNS, каждые 15 c.

Формат adapters() воспроизводит СТАРЫЙ (PowerShell) вывод 1:1 — по полям и
семантике (IPv4-only, как было у `-AddressFamily IPv4`), это специально
проверено на реальной машине: индекс, имя, описание, статус, physical, MAC,
скорость (текст вида "1 Gbps"), список IPv4, список DNS (IPv4) совпадают.

Известное расхождение с Get-NetAdapter (задокументировано, не устранено):
- `status` — GetAdaptersAddresses даёт только OperStatus (Up/Down/...), тогда
  как Get-NetAdapter различает ещё 'Disabled' (адаптер выключен вручную) —
  через WinAPI это неотличимо от 'Disconnected' (просто нет линка) без
  MIB_IF_ROW2 (GetIfEntry2), которую рискованно объявлять через ctypes
  (структура заканчивается десятком счётчиков трафика — ошибка в размере
  затрёт память). Фронт проверяет только `status === "Up"`, так что на
  поведение это не влияет — только на редкую текстовую метку.
- `physical` — Get-NetAdapter берёт это из NDIS-флага HardwareInterface
  (недоступен через GetAdaptersAddresses). Эвристика здесь — PnpInstanceId
  из реестра (ROOT\\*/SWD\\* = виртуальный, иначе физический), которая на
  живой машине совпала для реальных Ethernet/TAP/Tailscale/Hyper-V адаптеров,
  но для отдельных «псевдо-физических» виртуальных драйверов (например,
  Npcap Loopback Adapter, которому сам Windows зачем-то ставит Physical=True)
  даёт обратный результат. Некритично — это только суффикс "· вирт." в UI.
"""

import ctypes
import ctypes.wintypes as wintypes
import socket
import winreg

_iphlpapi = ctypes.windll.iphlpapi

_AF_UNSPEC = 0
_AF_INET = 2
_AF_INET6 = 23
_GAA_FLAG_SKIP_ANYCAST = 0x0002
_GAA_FLAG_SKIP_MULTICAST = 0x0004
_ERROR_BUFFER_OVERFLOW = 111
_ERROR_SUCCESS = 0
_IF_TYPE_SOFTWARE_LOOPBACK = 24  # псевдо-адаптер, Get-NetAdapter его не показывает

_OPERSTATUS_UP = 1
# NotPresent — устройство физически отсутствует (снятая флешка-модем и т.п.)
_OPERSTATUS_NOT_PRESENT = 6

_NETWORK_ADAPTER_CLASS_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Network"
    r"\{4d36e972-e325-11ce-bfc1-08002be10318}"
)
# префиксы PnpInstanceId software-перечисленных (не через шину PCI/USB) устройств
_VIRTUAL_PNP_PREFIXES = ("ROOT\\", "SWD\\")


class _SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]


class _IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass


_IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", ctypes.c_ulong),
    ("Flags", ctypes.c_ulong),
    ("Next", ctypes.POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", _SOCKET_ADDRESS),
    # дальше idём не читаем (PrefixOrigin/SuffixOrigin/…) — не нужно
]


class _IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
    pass


_IP_ADAPTER_DNS_SERVER_ADDRESS._fields_ = [
    ("Length", ctypes.c_ulong),
    ("Reserved", ctypes.c_ulong),
    ("Next", ctypes.POINTER(_IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("Address", _SOCKET_ADDRESS),
]


class _IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


# Урезанная IP_ADAPTER_ADDRESSES_LH: поля идут строго по нативному смещению
# вплоть до ReceiveLinkSpeed — то, что дальше (шлюзы, DHCP, GUID и т.п.), не
# читаем и в структуру не включаем. Это безопасно: элементы связаны списком
# указателей Next, которые ОС вычисляет по реальному (полному) размеру записи
# внутри своего буфера — наша усечённая структура смещений после Next не меняет.
_IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", ctypes.c_ulong),
    ("IfIndex", ctypes.c_ulong),
    ("Next", ctypes.POINTER(_IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(_IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", ctypes.c_ulong),
    ("Flags", ctypes.c_ulong),
    ("Mtu", ctypes.c_ulong),
    ("IfType", ctypes.c_ulong),
    ("OperStatus", ctypes.c_int),
    ("Ipv6IfIndex", ctypes.c_ulong),
    ("ZoneIndices", ctypes.c_ulong * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64),
    ("ReceiveLinkSpeed", ctypes.c_uint64),
]

_iphlpapi.GetAdaptersAddresses.argtypes = (
    wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG),
)
_iphlpapi.GetAdaptersAddresses.restype = wintypes.ULONG


def _sockaddr_ipv4(addr: _SOCKET_ADDRESS) -> str | None:
    if not addr.lpSockaddr:
        return None
    raw = ctypes.string_at(addr.lpSockaddr, addr.iSockaddrLength)
    if len(raw) < 8 or int.from_bytes(raw[0:2], "little") != _AF_INET:
        return None
    return socket.inet_ntoa(raw[4:8])


def _format_speed(bps: int) -> str:
    """Как LinkSpeed у Get-NetAdapter: наибольшая уместная единица, до 1 знака
    после запятой, без ".0" у круглых значений ("1 Gbps", "1.2 Gbps")."""
    for factor, unit in ((1e9, "Gbps"), (1e6, "Mbps"), (1e3, "Kbps")):
        if bps >= factor:
            val = bps / factor
            text = f"{val:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
    return f"{bps} bps"


def _mac_str(raw: bytes, length: int) -> str:
    return "-".join(f"{b:02X}" for b in raw[:length])


def _is_physical(adapter_guid: str | None) -> bool:
    """PnpInstanceId адаптера: ROOT\\*/SWD\\* — программно перечисленное
    устройство (виртуальный адаптер), иначе реальная шина (PCI/USB/...).

    Реальные PCI/USB-адаптеры всегда попадают в этот раздел реестра с валидным
    PnpInstanceId; отсутствие ключа (Hyper-V vEthernet-биндинги и т.п.) на
    практике встречается у виртуальных — поэтому дефолт при промахе не 'физический'.
    """
    if not adapter_guid:
        return False
    key_path = f"{_NETWORK_ADAPTER_CLASS_KEY}\\{adapter_guid}\\Connection"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            pnp_id, _ = winreg.QueryValueEx(k, "PnpInstanceId")
    except OSError:
        return False
    return not str(pnp_id).upper().startswith(_VIRTUAL_PNP_PREFIXES)


def _get_adapters_addresses() -> ctypes.Array:
    """Сырой буфер GetAdaptersAddresses — растим, пока хватит места."""
    size = wintypes.ULONG(15000)
    buf = ctypes.create_string_buffer(size.value)
    flags = _GAA_FLAG_SKIP_ANYCAST | _GAA_FLAG_SKIP_MULTICAST
    for _ in range(5):
        ret = _iphlpapi.GetAdaptersAddresses(
            _AF_UNSPEC, flags, None,
            ctypes.cast(buf, ctypes.POINTER(_IP_ADAPTER_ADDRESSES)), ctypes.byref(size),
        )
        if ret == _ERROR_SUCCESS:
            return buf
        if ret == _ERROR_BUFFER_OVERFLOW:
            buf = ctypes.create_string_buffer(size.value)
            continue
        raise OSError(f"GetAdaptersAddresses вернул код {ret}")
    raise OSError("GetAdaptersAddresses: не удалось подобрать размер буфера")


def adapters() -> list[dict]:
    """Все сетевые адаптеры — замена dns_jumper.manager.DnsJumper.adapters()
    (там же и сортировка: физические подключённые -> виртуальные подключённые
    -> отключённые)."""
    buf = _get_adapters_addresses()
    result = []
    cur = ctypes.cast(buf, ctypes.POINTER(_IP_ADAPTER_ADDRESSES))
    while cur:
        a = cur.contents
        if a.IfType == _IF_TYPE_SOFTWARE_LOOPBACK:
            cur = a.Next
            continue

        ipv4 = []
        ua = a.FirstUnicastAddress
        while ua:
            ip = _sockaddr_ipv4(ua.contents.Address)
            if ip:
                ipv4.append(ip)
            ua = ua.contents.Next

        dns = []
        da = a.FirstDnsServerAddress
        while da:
            ip = _sockaddr_ipv4(da.contents.Address)
            if ip:
                dns.append(ip)
            da = da.contents.Next

        guid = a.AdapterName.decode("ascii", "replace") if a.AdapterName else None
        result.append({
            "index": a.IfIndex,
            "name": a.FriendlyName or "",
            "desc": a.Description or "",
            "status": "Up" if a.OperStatus == _OPERSTATUS_UP else (
                "Not Present" if a.OperStatus == _OPERSTATUS_NOT_PRESENT else "Disconnected"
            ),
            "physical": _is_physical(guid),
            "mac": _mac_str(bytes(a.PhysicalAddress), a.PhysicalAddressLength),
            "speed": _format_speed(a.TransmitLinkSpeed),
            "ipv4": ipv4,
            "dns": dns,
            "guid": guid,
        })
        cur = a.Next

    result.sort(key=lambda x: (x["status"] != "Up", not x["physical"], x["name"]))
    return result
