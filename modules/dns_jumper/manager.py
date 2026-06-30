"""Переключатель системного DNS — аналог DNS Jumper внутри программы.

Список провайдеров в providers.json. Текущий DNS и переключение — через
PowerShell-командлеты DnsClient (нужны права администратора для записи).
Пинг — замер времени ответа на A-запрос через наш резолвер.
"""

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .. import appconfig, dns_providers
from ..hosts.resolver import ping_dns
from . import probe

# тест-домены пробы возможностей (config.json -> ключ dns_probe), с дефолтами
PROBE_DEFAULTS = {"bypass": ["chatgpt.com"], "ad": "doubleclick.net"}


def _ps(cmd: str) -> str:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "Ошибка PowerShell")
    return res.stdout.strip()


def _ps_json(cmd: str):
    out = _ps(cmd)
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]  # ConvertTo-Json об одном объекте отдаёт не массив


class DnsJumper:
    def list_providers(self) -> list[dict]:
        """Только провайдеры с IP-серверами (IPv4/IPv6) — их можно поставить
        системным DNS. Чисто DoH/DoT-провайдеры без IP тут не показываем:
        системному резолверу нужен IP (DoH-шаблон в Windows тоже привязан к IP)."""
        return [p for p in dns_providers.load_all() if p.get("servers") or p.get("ipv6")]

    def get_provider(self, provider_id: str) -> dict:
        return dns_providers.get(provider_id)

    def add_provider(self, name: str, servers, ipv6="", doh="", dot="",
                     unblock: bool = False, filtering: bool = False) -> dict:
        return dns_providers.add(name, servers=servers, ipv6=ipv6, doh=doh,
                                 dot=dot, unblock=unblock, filtering=filtering)

    def delete_provider(self, provider_id: str) -> None:
        dns_providers.delete(provider_id)

    def adapters(self) -> list[dict]:
        """Все сетевые адаптеры с полной инфой: статус, тип, MAC, IP, DNS (IPv4).

        Сортировка по полезности: физические подключённые -> виртуальные
        подключённые -> отключённые.
        """
        adapters = _ps_json(
            "Get-NetAdapter | ForEach-Object { "
            "$d = Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue; "
            "$ip = Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue; "
            "[pscustomobject]@{ index = $_.ifIndex; name = $_.Name; "
            "desc = $_.InterfaceDescription; status = [string]$_.Status; "
            "physical = -not $_.Virtual; mac = $_.MacAddress; speed = $_.LinkSpeed; "
            "ipv4 = @($ip.IPAddress); dns = @($d.ServerAddresses) } "
            "} | ConvertTo-Json -Depth 3"
        )
        adapters.sort(key=lambda a: (a["status"] != "Up", not a["physical"], a["name"]))
        return adapters

    def set_dns(self, adapter_index: int, provider_id: str) -> dict:
        """Ставит DNS провайдера: IPv4 + IPv6 разом. Если есть DoH-адрес — регистрирует
        его шаблон для каждого IP (системно) и включает шифрованный DNS (DoH) в Windows
        со строгим режимом (без отката на открытый UDP). Возвращает провайдера +
        флаг encrypted — реально ли включилось шифрование."""
        p = self.get_provider(provider_id)
        idx = int(adapter_index)
        all_ips = list(p.get("servers", [])) + list(p.get("ipv6", []))
        if not all_ips:
            raise ValueError("У провайдера нет IP-серверов — нечего ставить системным DNS")
        doh = p.get("doh", "")
        cmds = []
        if doh:
            # DoH-шаблон в Windows привязан к конкретному IP (системно) — регистрируем
            # его для каждого сервера провайдера, обновляя, если уже есть.
            for ip in all_ips:
                cmds.append(
                    f"if (Get-DnsClientDohServerAddress -ServerAddress '{ip}' "
                    f"-ErrorAction SilentlyContinue) {{ Set-DnsClientDohServerAddress "
                    f"-ServerAddress '{ip}' -DohTemplate '{doh}' -AllowFallbackToUdp $false "
                    f"-AutoUpgrade $true }} else {{ Add-DnsClientDohServerAddress "
                    f"-ServerAddress '{ip}' -DohTemplate '{doh}' -AllowFallbackToUdp $false "
                    f"-AutoUpgrade $true }}"
                )
        addr_list = ",".join(f"'{ip}'" for ip in all_ips)
        cmds.append(f"Set-DnsClientServerAddress -InterfaceIndex {idx} "
                    f"-ServerAddresses {addr_list}")
        cmds.append("Clear-DnsClientCache")
        _ps("; ".join(cmds))
        return {**p, "encrypted": bool(doh)}

    def reset_dns(self, adapter_index: int) -> None:
        """Возврат на DNS от DHCP (как «Восстановить» в DNS Jumper)."""
        _ps(
            f"Set-DnsClientServerAddress -InterfaceIndex {int(adapter_index)} "
            f"-ResetServerAddresses; Clear-DnsClientCache"
        )

    def ping_all(self) -> list[dict]:
        """Пингует все серверы всех провайдеров параллельно."""
        providers = self.list_providers()
        jobs = [(p["id"], ip) for p in providers for ip in p["servers"]]
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda j: (j[0], ping_dns(j[1])), jobs))
        by_provider: dict[str, list] = {}
        for pid, r in results:
            by_provider.setdefault(pid, []).append(r)
        return [
            {"id": p["id"], "name": p["name"], "servers": by_provider.get(p["id"], [])}
            for p in providers
        ]

    def ping_one(self, provider_id: str) -> dict:
        """Пинг серверов ОДНОГО провайдера (его IP — параллельно). Для покадрового
        автопинга, где у каждого провайдера свой цикл раз в секунду."""
        p = self.get_provider(provider_id)
        servers = p.get("servers", [])
        with ThreadPoolExecutor(max_workers=max(1, len(servers))) as pool:
            results = list(pool.map(ping_dns, servers))
        return {"id": p["id"], "name": p["name"], "servers": results}

    # --- проба возможностей (DNSSEC / обход / реклама) -----------------------

    def probe_config(self) -> dict:
        """Тест-домены пробы из config.json (с дефолтами)."""
        cfg = appconfig.load().get("dns_probe") or {}
        return {"bypass": cfg.get("bypass") or list(PROBE_DEFAULTS["bypass"]),
                "ad": cfg.get("ad", PROBE_DEFAULTS["ad"])}

    def set_probe_config(self, bypass, ad) -> dict:
        if not isinstance(bypass, list):
            bypass = re.split(r"[\s,;]+", str(bypass or ""))
        bypass = [d.strip().lower().lstrip(".") for d in bypass if d and d.strip()]
        appconfig.set_value("dns_probe", {"bypass": bypass, "ad": str(ad or "").strip().lower()})
        return self.probe_config()

    def probe_provider(self, provider_id: str) -> dict:
        """Живая проба возможностей провайдера по настроенным тест-доменам."""
        p = self.get_provider(provider_id)
        servers = list(p.get("servers", [])) + list(p.get("ipv6", []))
        cfg = self.probe_config()
        result = probe.probe(servers, cfg["bypass"], cfg["ad"])
        return {"id": p["id"], "name": p["name"], **result}
