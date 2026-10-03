"""Переключатель системного DNS — аналог DNS Jumper внутри программы.

Список провайдеров в providers.json. Текущий DNS и переключение — через
PowerShell-командлеты DnsClient (нужны права администратора для записи).
Пинг — замер времени ответа на A-запрос через наш резолвер.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraValueError

import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .. import appconfig, applog, dns_providers, paths, provider_registry
from ..hosts.resolver import ping_dns
from . import netinfo, probe

# тест-домены пробы возможностей (config.json -> ключ dns_probe), с дефолтами
PROBE_DEFAULTS = {"bypass": ["chatgpt.com"], "ad": "doubleclick.net"}

# индексы адаптеров, где DNS поставили мы: «Выключить всё» сбрасывает только их и не
# трогает адаптеры, у которых DNS выставлен пользователем или провайдером
CHANGED_PATH = paths.data_path("dns_changed.json")

# пробное применение DNS: сколько секунд даём на «оставить» до автоматического отката
TRIAL_DEFAULT, TRIAL_MIN, TRIAL_MAX = 15, 5, 120


def _ps(cmd: str) -> str:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or _tr('msg.modules.dns_jumper.manager.powershell_error'))
    return res.stdout.strip()


def _ps_json(cmd: str):
    out = _ps(cmd)
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]  # ConvertTo-Json об одном объекте отдаёт не массив


class DnsJumper:
    def __init__(self):
        self._trials: dict[int, dict] = {}   # индекс адаптера -> пробное применение в ожидании ответа
        self._trial_lock = threading.RLock()

    def list_providers(self) -> list[dict]:
        """Только провайдеры с IP-серверами (IPv4/IPv6) — их можно поставить
        системным DNS. Чисто DoH/DoT-провайдеры без IP тут не показываем:
        системному резолверу нужен IP (DoH-шаблон в Windows тоже привязан к IP)."""
        hidden = provider_registry.hidden_ids()
        return [p for p in dns_providers.load_all()
                if (p.get("servers") or p.get("ipv6")) and not (p.get("builtin") and p["id"] in hidden)]

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

        Раньше это было Get-NetAdapter + Get-DnsClientServerAddress +
        Get-NetIPAddress — секунды на поднятие powershell.exe при каждом опросе
        вкладки DNS. netinfo.adapters() даёт тот же формат через WinAPI
        (GetAdaptersAddresses) без подпроцесса; известные мелкие расхождения
        с Get-NetAdapter описаны в модуле modules/dns_jumper/netinfo.py.
        Резерв на PowerShell — если WinAPI-путь неожиданно упал.
        """
        try:
            return netinfo.adapters()
        except OSError:
            return self._adapters_ps()

    def _adapters_ps(self) -> list[dict]:
        adapters = _ps_json(
            "Get-NetAdapter | ForEach-Object { "
            "$d = Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue; "
            "$ip = Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue; "
            "[pscustomobject]@{ index = $_.ifIndex; name = $_.Name; "
            "desc = $_.InterfaceDescription; status = [string]$_.Status; "
            "physical = -not $_.Virtual; mac = $_.MacAddress; speed = $_.LinkSpeed; "
            "ipv4 = @($ip.IPAddress); dns = @($d.ServerAddresses); guid = $_.InterfaceGuid } "
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
            raise ChimeraValueError('err.dns_jumper.manager.the_provider_has_no_ip_servers_to_use_for_system')
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
        self._remember(idx, True)
        return {**p, "encrypted": bool(doh)}

    def reset_dns(self, adapter_index: int) -> None:
        """Возврат на DNS от DHCP (как «Восстановить» в DNS Jumper)."""
        _ps(
            f"Set-DnsClientServerAddress -InterfaceIndex {int(adapter_index)} "
            f"-ResetServerAddresses; Clear-DnsClientCache"
        )
        self._remember(int(adapter_index), False)

    # --- пробное применение с автооткатом --------------------------------------
    # Смена DNS может оставить без интернета, и тогда «Оставить» некому нажать. Поэтому
    # прежнее состояние адаптера запоминается, а таймер в бэкенде (он работает, даже
    # если окно закрыли) сам вернёт его, если за N секунд DNS не подтвердили.

    _now = staticmethod(time.time)

    def _schedule(self, seconds, fn):
        t = threading.Timer(seconds, fn)
        t.daemon = True
        t.start()
        return t

    @staticmethod
    def _is_static(guid) -> bool | None:
        """Заданы ли DNS-серверы адаптера вручную (True) или приходят по DHCP (False).
        None — узнать не удалось. Смотрим реестр: значение NameServer у интерфейса
        пусто при DHCP."""
        if not guid:
            return None
        import winreg
        path = rf"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{guid}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as k:
                try:
                    value, _ = winreg.QueryValueEx(k, "NameServer")
                except FileNotFoundError:
                    return False
        except OSError:
            return None
        return bool(str(value).strip())

    def _snapshot(self, idx: int) -> dict:
        for a in self.adapters():
            if a.get("index") == idx:
                return {"dns": list(a.get("dns") or []), "static": self._is_static(a.get("guid"))}
        return {"dns": [], "static": None}

    def _public_trial(self, t: dict) -> dict:
        return {"adapter": t["adapter"], "provider": t["provider"], "deadline": t["deadline"],
                "seconds_left": max(0, int(round(t["deadline"] - self._now()))),
                "previous": t["previous"]}

    def set_dns_trial(self, adapter_index: int, provider_id: str, seconds: int = TRIAL_DEFAULT) -> dict:
        """set_dns + таймер отката. Повторная проба на том же адаптере не теряет исходное
        состояние: откат вернёт то, что было до первой пробы."""
        idx = int(adapter_index)
        seconds = max(TRIAL_MIN, min(TRIAL_MAX, int(seconds)))
        with self._trial_lock:
            existing = self._trials.get(idx)
            previous = existing["previous"] if existing else self._snapshot(idx)
            was_ours = existing["was_ours"] if existing else idx in self.changed_adapters()
            p = self.set_dns(idx, provider_id)   # не вышло — исключение, таймер не взводится
            if existing:
                existing["timer"].cancel()
            trial = {"adapter": idx, "provider": provider_id, "previous": previous,
                     "was_ours": was_ours, "deadline": self._now() + seconds}
            trial["timer"] = self._schedule(seconds, lambda i=idx: self._expire(i))
            self._trials[idx] = trial
            return {**p, "trial": self._public_trial(trial)}

    def _expire(self, idx: int) -> None:
        try:
            self.trial_revert(idx)
        except Exception as e:  # поток таймера: сбой отката виден в журнале, а не теряется
            applog.write(f"Автооткат DNS на адаптере {idx} не удался: {e}")

    def trials(self) -> list[dict]:
        with self._trial_lock:
            return [self._public_trial(t) for t in self._trials.values()]

    def trial_confirm(self, adapter_index=None) -> dict:
        """Оставить новый DNS: таймер отменяется, откат не произойдёт."""
        with self._trial_lock:
            keys = [int(adapter_index)] if adapter_index is not None else list(self._trials)
            confirmed = []
            for idx in keys:
                t = self._trials.pop(idx, None)
                if t:
                    t["timer"].cancel()
                    confirmed.append(idx)
        return {"confirmed": confirmed}

    def trial_revert(self, adapter_index=None) -> dict:
        """Вернуть прежнее состояние адаптера: DHCP или прежние статические серверы."""
        with self._trial_lock:
            keys = [int(adapter_index)] if adapter_index is not None else list(self._trials)
            reverted = []
            for idx in keys:
                t = self._trials.pop(idx, None)
                if not t:
                    continue
                t["timer"].cancel()
                prev = t["previous"]
                if prev.get("static") and prev.get("dns"):
                    servers = ",".join(f"'{ip}'" for ip in prev["dns"])
                    _ps(f"Set-DnsClientServerAddress -InterfaceIndex {idx} -ServerAddresses {servers}; "
                        f"Clear-DnsClientCache")
                    self._remember(idx, t["was_ours"])
                else:
                    self.reset_dns(idx)   # DHCP, а если статус неизвестен — тоже DHCP: безопаснее всего
                reverted.append(idx)
        return {"reverted": reverted}

    # --- адаптеры, где DNS поставили мы ---------------------------------------

    def changed_adapters(self) -> list[int]:
        try:
            data = json.loads(CHANGED_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return sorted({int(i) for i in data if isinstance(i, int)}) if isinstance(data, list) else []

    def _remember(self, idx: int, changed: bool) -> None:
        current = set(self.changed_adapters())
        current.add(idx) if changed else current.discard(idx)
        try:
            CHANGED_PATH.write_text(json.dumps(sorted(current)), encoding="utf-8")
        except OSError:
            pass  # учёт вспомогательный: не удалось записать — DNS всё равно уже применён

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
