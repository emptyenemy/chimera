"""Прокси на sing-box: системный (PAC), выборочный TUN и полный TUN.

Режимы (config["mode"]):
  pac   — системный прокси: PAC-файл в настройках WinINet шлёт в локальный SOCKS
          только домены/IP из выбранных списков (modules/domains). Его читают
          браузеры и программы, берущие системные настройки прокси. Без админа.
  split — выборочный TUN: трафик всей системы идёт через виртуальный адаптер, но
          в прокси уходят только выбранные приложения (по имени процесса) и
          выбранные списки, остальное — напрямую. Ловит и программы, которые
          системный прокси игнорируют (Store-приложения, Discord). Нужен админ.
  tun   — полный TUN: весь трафик через прокси, кроме локальной сети. Нужен админ.

sing-box.exe тянется одним пиннутым релизом в bin/sing-box/ (см. SINGBOX_*).
Настройки (ссылка, списки, приложения, режим, autostart) — в data/proxy.json.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraFileNotFoundError, ChimeraRuntimeError, ChimeraValueError

import ctypes
import hashlib
import io
import json
import os
import subprocess
import threading
import time
import urllib.request
import winreg
import zipfile
from pathlib import Path

from modules import domains, paths, winproc
from . import parser

ROOT = Path(__file__).parent.parent.parent
SINGBOX_DIR = ROOT / "bin" / "sing-box"
SINGBOX_EXE = SINGBOX_DIR / "sing-box.exe"
SINGBOX_EXE_NEW = SINGBOX_DIR / "sing-box.exe.new"  # сюда качаем, пока не проверили хеш
SINGBOX_EXE_OLD = SINGBOX_DIR / "sing-box.exe.old"  # сюда уезжает старый exe, если он занят
CONFIG_PATH = paths.data_path("singbox-config.json")
paths.migrate(Path(__file__).parent / "singbox-config.json", CONFIG_PATH)
STATE_PATH = paths.data_path("proxy.json")
paths.migrate(Path(__file__).parent / "state.json", STATE_PATH)  # разовый перенос со старого места
LOG_PATH = paths.log_path("proxy.log")
paths.migrate(Path(__file__).parent / "proxy.log", LOG_PATH)
PAC_PATH = paths.data_path("proxy.pac")
paths.migrate(Path(__file__).parent / "proxy.pac", PAC_PATH)

# Домены и подсети из выбранных списков лежат не в конфиге, а в локальных файлах правил
# sing-box: ядро следит за ними и подхватывает правку без перезапуска (проверено на
# 1.14.2 — за доли секунды, в том числе при замене файла целиком).
DOMAINS_RULESET_PATH = paths.data_path("singbox-domains.json")
IPS_RULESET_PATH = paths.data_path("singbox-ips.json")
DOMAINS_TAG = "chimera-domains"
IPS_TAG = "chimera-ips"
# Пустое условие в правиле — ошибка или «подходит всё», поэтому пустые списки пишем
# заглушками, которые не совпадут ни с чем (TEST-NET-3 и зарезервированный .invalid).
DOMAIN_PLACEHOLDER = "chimera.invalid"
IP_PLACEHOLDER = "203.0.113.113/32"

# ветка реестра WinINet: туда пишем AutoConfigURL, чтобы браузеры подхватили PAC
_INET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# Пиннутая версия: схема конфига sing-box заметно менялась по версиям, поэтому
# бинарь и генератор конфига должны соответствовать друг другу.
SINGBOX_VERSION = "1.14.2"
SINGBOX_URL = (
    f"https://github.com/SagerNet/sing-box/releases/download/v{SINGBOX_VERSION}/"
    f"sing-box-{SINGBOX_VERSION}-windows-amd64.zip"
)
# sha256 zip-архива релиза (сверен с полем digest ассета в GitHub API и повторным
# скачиванием). Меняется вместе с SINGBOX_VERSION при обновлении версии.
SINGBOX_SHA256 = "c2d8bfff918755808781dfdeeb8581b6c91eb3a243d9a7b55483cfc0c0684d32"

# mode: "pac" | "split" | "tun" — см. докстринг модуля; apps — имена процессов для split.
DEFAULTS = {"link": "", "lists": [], "apps": [], "autostart": False, "mode": "pac", "socks_port": 2080}
MODES = ("pac", "split", "tun")

# Общий TUN-адаптер выборочного и полного режимов.
_TUN_INBOUND = {
    "type": "tun", "tag": "tun-in",
    "address": ["172.18.0.1/30"],
    "auto_route": True, "strict_route": True,
    "stack": "system", "mtu": 9000,
}

_CREATE_NO_WINDOW = 0x08000000


def _cleanup_old_exe() -> None:
    """Подчищает sing-box.exe.old, оставшийся от предыдущего обновления, — если он
    ещё занят процессом, который на нём доработал, тихо оставляем как есть и
    пробуем при следующем старте/скачивании."""
    try:
        SINGBOX_EXE_OLD.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass  # занят — приберём в другой раз


class ProxyManager:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._log = None
        self._error: str | None = None
        self._sysproxy_on = False  # проставили ли мы PAC в системный прокси
        self._lock = threading.RLock()
        self.config = self._load()
        self._core_version_cache: str | None = None  # версия бинаря меняется только при download_core
        self._core_version_cached = False
        _cleanup_old_exe()  # подчистить sing-box.exe.old, если он остался с прошлого обновления

    # --- конфиг (state.json) -------------------------------------------------

    def _load(self) -> dict:
        data = dict(DEFAULTS)
        if STATE_PATH.exists():
            try:
                data.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError, OSError):
                pass
        return data

    def _save(self) -> None:
        STATE_PATH.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )

    def set_link(self, raw: str) -> dict:
        raw = (raw or "").strip()
        if raw:
            parser.parse_link(raw)  # валидация: бросит ValueError, если кривая
        self.config["link"] = raw
        self._save()
        if self.running:
            self.restart()
        return self.state()

    def set_lists(self, names) -> dict:
        valid = {i["name"] for i in domains.list_info()}
        self.config["lists"] = [n for n in (names or []) if n in valid]
        self._save()
        self.reload_lists()  # без перезапуска: ядро перечитает файлы правил само
        return self.state()

    def reload_lists(self) -> None:
        """Применяет текущие списки к работающему прокси: переписывает файлы правил
        (ядро подхватит их само), а в PAC-режиме ещё PAC и уведомляет браузеры.
        Остановленному прокси ничего не нужно — файлы допишет start()."""
        with self._lock:
            if not self.running:
                return
            self._write_rulesets()
            if self._pac_mode:
                self._write_pac()
                self._wininet_refresh()

    def _write_rulesets(self) -> None:
        """Пишет домены и подсети выбранных списков в файлы правил sing-box.
        Замена файла атомарная (tmp + os.replace): ядро не должно прочесть половину."""
        dom, nets = self._split()
        for path, key, items, placeholder in (
            (DOMAINS_RULESET_PATH, "domain_suffix", dom, DOMAIN_PLACEHOLDER),
            (IPS_RULESET_PATH, "ip_cidr", nets, IP_PLACEHOLDER),
        ):
            body = {"version": 3, "rules": [{key: list(items) or [placeholder]}]}
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    @staticmethod
    def _ruleset_refs() -> list[dict]:
        return [
            {"type": "local", "tag": DOMAINS_TAG, "format": "source", "path": str(DOMAINS_RULESET_PATH)},
            {"type": "local", "tag": IPS_TAG, "format": "source", "path": str(IPS_RULESET_PATH)},
        ]

    def set_autostart(self, value: bool) -> dict:
        self.config["autostart"] = bool(value)
        self._save()
        return self.state()

    def set_apps(self, names) -> dict:
        """Приложения для выборочного TUN — голые имена образов (как в диспетчере
        задач: Discord.exe). sing-box сравнивает process_name с именем файла, так что
        пути и имена без .exe сюда не пускаем; повторы — без учёта регистра."""
        apps, seen = [], set()
        for raw in names or []:
            name = str(raw).strip()
            if (not name.lower().endswith(".exe") or len(name) <= 4
                    or any(c in name for c in '\\/:*?"<>|')):
                continue
            if name.lower() not in seen:
                seen.add(name.lower())
                apps.append(name)
        self.config["apps"] = apps
        self._save()
        if self.running and self.config.get("mode") == "split":
            self.restart()
        return self.state()

    def set_mode(self, mode: str) -> dict:
        if mode not in MODES:
            raise ChimeraValueError('err.proxy.manager.mode_must_be_pac_split_or_tun')
        self.config["mode"] = mode
        self._save()
        if self.running:
            self.restart()
        return self.state()

    # --- бинарь sing-box -----------------------------------------------------

    def core_version(self) -> str | None:
        """Версия sing-box.exe. Кэшируем: запуск бинаря на каждый опрос дашборда
        (раз в 3 c, таймаут до 5 c) — главный источник лагов. Меняется только после
        download_core(), который сбрасывает кэш. Отсутствие бинаря не кэшируем —
        его могут скачать позже."""
        if self._core_version_cached:
            return self._core_version_cache
        if not SINGBOX_EXE.exists():
            return None
        try:
            out = subprocess.run(
                [str(SINGBOX_EXE), "version"],
                capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW,
                timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        ver = None
        for line in out.splitlines():
            if "version" in line.lower():
                parts = line.split()
                ver = parts[-1] if parts else None
                break
        ver = ver or out.strip() or None
        self._core_version_cache = ver
        self._core_version_cached = True
        return ver

    def download_core(self) -> dict:
        """Качает пиннутый релиз sing-box и подменяет им sing-box.exe в bin/sing-box/.

        Пишем сначала во временный sing-box.exe.new — если прокси запущен, сам
        sing-box.exe занят и прямая перезапись падает PermissionError. Windows,
        в отличие от перезаписи, разрешает ПЕРЕИМЕНОВАТЬ запущенный exe — на этот
        случай старый файл уезжает в sing-box.exe.old (работающий процесс
        доработает на нём), а новый становится sing-box.exe. Новая версия
        подхватится только после перезапуска прокси — сигналим об этом полем
        restart_required (и человекочитаемым message) в ответе.
        """
        SINGBOX_DIR.mkdir(parents=True, exist_ok=True)
        _cleanup_old_exe()
        req = urllib.request.Request(SINGBOX_URL, headers={"User-Agent": "chimera"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != SINGBOX_SHA256:
            raise ChimeraRuntimeError('err.proxy.manager.the_downloaded_sing_box_archive_failed_sha256_ve', p0=SINGBOX_VERSION)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next((n for n in z.namelist() if n.endswith("sing-box.exe")), None)
            if not name:
                raise ChimeraRuntimeError('err.proxy.manager.the_archive_does_not_contain_sing_box_exe')
            with z.open(name) as src, open(SINGBOX_EXE_NEW, "wb") as dst:
                dst.write(src.read())

        restart_required = False
        try:
            os.replace(SINGBOX_EXE_NEW, SINGBOX_EXE)
        except PermissionError:
            # целевой exe занят запущенным прокси — перезаписать нельзя, но
            # переименовать можно: старый уходит в сторону, новый встаёт на его место
            try:
                os.replace(SINGBOX_EXE, SINGBOX_EXE_OLD)
                os.replace(SINGBOX_EXE_NEW, SINGBOX_EXE)
            except OSError as e:
                raise ChimeraRuntimeError('err.proxy.manager.could_not_replace_sing_box_exe', p0=e) from e
            restart_required = True

        self._core_version_cached = False  # скачали новый бинарь — пересчитать версию
        result = {"present": True, "version": self.core_version()}
        if restart_required:
            result["restart_required"] = True
            result["message"] = (
                _tr('msg.modules.proxy.manager.sing_box_updated_restart_the_running_proxy_to_us')
            )
        return result

    # --- генерация конфига sing-box -----------------------------------------

    def _split(self) -> tuple[list[str], list[str]]:
        """Выбранные списки -> (домены для domain_suffix, подсети для ip_cidr).

        IP обязаны ехать отдельным правилом: у соединения на голый адрес нет ни SNI,
        ни Host, поэтому domain_suffix по нему не сработает и трафик утёк бы в direct.
        """
        if not self.config["lists"]:
            return [], []
        return domains.split_lists(self.config["lists"])

    def _domains(self) -> list[str]:
        return self._split()[0]

    @property
    def _pac_mode(self) -> bool:
        # незнакомое значение (руками поправленный proxy.json) — как PAC: он без админа
        return self.config.get("mode", "pac") not in ("split", "tun")

    @property
    def needs_admin(self) -> bool:
        """TUN (выборочный и полный) поднимает сетевой адаптер — без админа не выйдет."""
        return not self._pac_mode

    def build_config(self) -> dict:
        if not self.config["link"]:
            raise ChimeraValueError('err.proxy.manager.enter_a_proxy_link_vless_etc')
        proxy_ob = dict(parser.parse_link(self.config["link"])["outbound"])
        proxy_ob["tag"] = "proxy"

        dns_servers = [
            {"tag": "dns-proxy", "type": "https", "server": "1.1.1.1", "detour": "proxy"},
            {"tag": "dns-direct", "type": "local"},
        ]

        if self._pac_mode:
            # PAC: выборочно — через прокси идут ТОЛЬКО записи из выбранных списков,
            # остальной трафик ядро вообще не видит (PAC отправляет в SOCKS лишь их).
            # правила ссылаются на файлы всегда, даже при пустых списках: домен,
            # добавленный позже, ляжет в файл и подхватится без перезапуска ядра
            dns = {
                "servers": dns_servers,
                # IP в DNS-правилах не нужны — их резолвить нечего
                "rules": [{"rule_set": [DOMAINS_TAG], "server": "dns-proxy"}],
                "final": "dns-direct",
                "strategy": "prefer_ipv4",
            }
            inbound = {
                "type": "mixed", "tag": "mixed-in",
                "listen": "127.0.0.1", "listen_port": int(self.config["socks_port"]),
            }
            route_rules = [
                {"action": "sniff"},
                {"rule_set": [DOMAINS_TAG], "outbound": "proxy"},
                {"rule_set": [IPS_TAG], "outbound": "proxy"},
            ]
            route = {
                "rule_set": self._ruleset_refs(),
                "rules": route_rules,
                "final": "direct",  # не-наши домены (если влезут) — мимо
                "default_domain_resolver": {"server": "dns-direct"},
            }
        elif self.config.get("mode") == "split":
            dns, inbound, route = self._split_tun_config(dns_servers)
        else:
            # TUN: полный VPN — ВЕСЬ трафик и DNS идут через прокси (списки
            # игнорируются), напрямую остаётся только локальная сеть (LAN/localhost),
            # иначе отвалятся роутер/принтеры/соседние устройства.
            dns = {
                "servers": dns_servers,
                "final": "dns-proxy",  # весь DNS через прокси — без утечек
                "strategy": "prefer_ipv4",
            }
            inbound = dict(_TUN_INBOUND)
            route = {
                "rules": [
                    {"action": "sniff"},
                    {"protocol": "dns", "action": "hijack-dns"},
                    {"ip_is_private": True, "outbound": "direct"},
                ],
                "final": "proxy",  # всё, кроме локалки, — в туннель
                "auto_detect_interface": True,
                "default_domain_resolver": {"server": "dns-proxy"},
            }

        return {
            "log": {"level": "info", "timestamp": True},
            "dns": dns,
            "inbounds": [inbound],
            "outbounds": [proxy_ob, {"type": "direct", "tag": "direct"}],
            "route": route,
        }

    def _split_tun_config(self, dns_servers: list[dict]) -> tuple[dict, dict, dict]:
        """Выборочный TUN: адаптер ловит весь трафик системы, но в прокси уходят
        только выбранные приложения и списки, остальное (игры и т.п.) — напрямую.

        Приложения узнаются по имени процесса (route.find_process + process_name).
        Домены — по SNI (sniff), а соединения без SNI (свой протокол у чата WhatsApp,
        голый TCP) — через dns.reverse_mapping: ядро помнит, какой IP какому домену
        выдало, поэтому DNS гоним через себя (hijack-dns). Запись, закэшированная
        Windows до старта ядра, мимо него — такие соединения узнаются по домену
        только после истечения TTL.

        DNS-запросы в Windows шлёт системная служба, а не само приложение, поэтому
        process_name в DNS-правилах ловит лишь тех, кто резолвит сам (async DNS у
        Chrome); остальной DNS приложений — напрямую, что не мешает: их соединения
        всё равно уходят в прокси по имени процесса."""
        apps = list(self.config.get("apps") or [])

        dns_rules = []
        if apps:
            dns_rules.append({"process_name": apps, "server": "dns-proxy"})
        dns_rules.append({"rule_set": [DOMAINS_TAG], "server": "dns-proxy"})
        dns = {
            "servers": dns_servers,
            "rules": dns_rules,
            "final": "dns-direct",
            "strategy": "prefer_ipv4",
            "reverse_mapping": True,
        }

        rules = [
            {"action": "sniff"},
            {"protocol": "dns", "action": "hijack-dns"},
            # локалка раньше правил по приложениям: браузер ходит и на роутер
            {"ip_is_private": True, "outbound": "direct"},
        ]
        if apps:
            rules.append({"process_name": apps, "outbound": "proxy"})
        rules.append({"rule_set": [DOMAINS_TAG], "outbound": "proxy"})
        rules.append({"rule_set": [IPS_TAG], "outbound": "proxy"})
        route = {
            "rule_set": self._ruleset_refs(),
            "rules": rules,
            "final": "direct",
            "find_process": True,
            "auto_detect_interface": True,
            "default_domain_resolver": {"server": "dns-direct"},
        }
        return dns, dict(_TUN_INBOUND), route

    # --- PAC-файл и системный прокси (только режим pac) ----------------------

    def _write_pac(self) -> None:
        """Генерит PAC: наши домены и IP → SOCKS5, всё остальное → DIRECT."""
        dom_list, nets = self._split()
        dom = [d.replace('"', "") for d in dom_list]

        # v4-подсети проверяем через isInNet (пара «сеть, маска»), одиночные v6 —
        # строгим сравнением. Более широкие v6-подсети PAC штатно проверить не умеет
        # (isInNet — только IPv4), они остаются рабочими в TUN-режиме.
        v4, v6 = [], []
        for n in nets:
            net = domains.as_network(n)
            if net is None:
                continue
            if net.version == 4:
                v4.append((str(net.network_address), str(net.netmask)))
            elif net.prefixlen == 128:
                v6.append(str(net.network_address))

        port = int(self.config["socks_port"])
        # именно SOCKS5 (не SOCKS4): браузер шлёт имя хоста в прокси, а не резолвит
        # сам локально — иначе для наших доменов сработал бы заблокированный DNS
        proxy = f"SOCKS5 127.0.0.1:{port}; DIRECT"
        arr = ", ".join('"%s"' % d for d in dom)
        exact = ", ".join('"%s"' % a for a in v6)
        nets_js = ", ".join('["%s", "%s"]' % pair for pair in v4)
        pac = (
            "function FindProxyForURL(url, host) {\n"
            '  var P = "%s";\n'
            "  var d = [%s];\n"
            "  for (var i = 0; i < d.length; i++) {\n"
            '    if (host === d[i] || host.slice(-(d[i].length + 1)) === "." + d[i]) return P;\n'
            "  }\n"
            "  var x = [%s];\n"
            "  for (var i = 0; i < x.length; i++) { if (host === x[i]) return P; }\n"
            "  var n = [%s];\n"
            # isInNet с доменным host резолвит его через DNS (медленно и мимо прокси),
            # поэтому подсети проверяем, только когда host — уже готовый IPv4-литерал
            "  if (/^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$/.test(host)) {\n"
            "    for (var i = 0; i < n.length; i++) {\n"
            "      if (isInNet(host, n[i][0], n[i][1])) return P;\n"
            "    }\n"
            "  }\n"
            '  return "DIRECT";\n'
            "}\n"
        ) % (proxy, arr, exact, nets_js)
        PAC_PATH.write_text(pac, encoding="utf-8")

    def _pac_url(self) -> str:
        return "file:///" + str(PAC_PATH).replace("\\", "/")

    @staticmethod
    def _wininet_refresh() -> None:
        """Уведомляем WinINet — PAC подхватывается без перезапуска браузера."""
        try:
            wininet = ctypes.windll.wininet
            wininet.InternetSetOptionW(0, 39, 0, 0)  # SETTINGS_CHANGED
            wininet.InternetSetOptionW(0, 37, 0, 0)  # REFRESH
        except (OSError, AttributeError):
            pass

    def _enable_system_proxy(self) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_SETTINGS, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "AutoConfigURL", 0, winreg.REG_SZ, self._pac_url())
        self._sysproxy_on = True
        self._wininet_refresh()

    def _disable_system_proxy(self) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_SETTINGS, 0,
                                winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, "AutoConfigURL")
                except FileNotFoundError:
                    pass
            self._wininet_refresh()
        except OSError:
            pass
        self._sysproxy_on = False

    @staticmethod
    def _read_autoconfig_url() -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_SETTINGS, 0, winreg.KEY_READ) as k:
                value, _ = winreg.QueryValueEx(k, "AutoConfigURL")
        except OSError:
            return None
        return str(value) or None

    def cleanup_stale_system_proxy(self) -> bool:
        """Снимает PAC из системного прокси, если он наш, а прокси не запущен.

        Так остаётся после аварийного завершения программы: браузеры слали бы наши
        домены на мёртвый SOCKS-порт, и сайты из списков переставали открываться.
        Чужой PAC (корпоративный) не трогаем. True — что-то сняли."""
        if self.running:
            return False
        if self._read_autoconfig_url() != self._pac_url():
            return False
        self._disable_system_proxy()
        return True

    # --- жизненный цикл ------------------------------------------------------

    @property
    def _ours_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def running(self) -> bool:
        return self._ours_alive or bool(self._system_pids())

    @staticmethod
    def _system_pids() -> list[int]:
        """PID всех живых sing-box.exe — ToolHelp32Snapshot вместо tasklist
        (см. modules/winproc.py): тот же охват чужих/прошлосессионных процессов,
        но без подпроцесса на каждый опрос хаба (раз в 2-3 c)."""
        try:
            return winproc.pids_by_name(SINGBOX_EXE.name)
        except OSError:
            return []

    def start(self) -> dict:
        with self._lock:
            if self.running:
                self.stop()
            if not SINGBOX_EXE.exists():
                raise ChimeraFileNotFoundError('err.proxy.manager.sing_box_is_not_installed_click_download_sing_bo')
            cfg = self.build_config()
            self._write_rulesets()  # конфиг ссылается на эти файлы — они должны быть до старта ядра
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            if self._pac_mode:
                self._write_pac()
            self._error = None
            self._log = open(LOG_PATH, "w", encoding="utf-8")
            try:
                self._proc = subprocess.Popen(
                    [str(SINGBOX_EXE), "run", "-c", str(CONFIG_PATH)],
                    cwd=str(SINGBOX_DIR),
                    stdout=self._log, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except OSError as e:
                self._close_log()
                self._proc = None
                raise ChimeraRuntimeError('err.proxy.manager.could_not_start_sing_box', p0=e) from e
            # ловим мгновенную смерть (кривой конфиг, нет прав на TUN, занят адаптер/порт)
            time.sleep(1.5)
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self._proc = None
                self._close_log()
                self._error = self._read_error(code)
                raise RuntimeError(self._error)
            # ядро поднялось — теперь заворачиваем браузеры на PAC
            if self._pac_mode:
                self._enable_system_proxy()
            return self.state()

    def _read_error(self, code: int) -> str:
        lines = [ln.strip() for ln in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        tail = " | ".join(lines[-4:]) if lines else _tr('msg.modules.proxy.manager.no_output')
        return _tr('msg.modules.proxy.manager.sing_box_exited_code', p0=f'{code}', p1=f'{tail}')

    def log_read(self, offset: int = 0) -> dict:
        """Инкрементальное чтение лога sing-box (живой стрим в UI)."""
        from modules import logutil
        return logutil.read_from(LOG_PATH, offset)

    def _close_log(self) -> None:
        if self._log:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    def stop(self) -> dict:
        with self._lock:
            # сперва снимаем PAC из системного прокси — иначе браузер будет слать
            # наши домены на уже мёртвый SOCKS-порт
            self._disable_system_proxy()
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()  # sing-box по SIGTERM снимает TUN и маршруты
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            self._close_log()
            self._kill_leftovers()
            return self.state()

    @staticmethod
    def _kill_leftovers() -> None:
        if not ProxyManager._system_pids():
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "sing-box.exe"],
                capture_output=True, creationflags=_CREATE_NO_WINDOW,
            )
        except OSError:
            pass
        for _ in range(20):
            if not ProxyManager._system_pids():
                return
            time.sleep(0.15)

    def restart(self) -> dict:
        self.stop()
        time.sleep(0.2)
        return self.start()

    # --- состояние для UI ----------------------------------------------------

    def state(self) -> dict:
        parsed = err = None
        if self.config["link"]:
            try:
                p = parser.parse_link(self.config["link"])
                transport = p["outbound"].get("transport", {}).get("type", "tcp")
                parsed = {"label": p["label"], "protocol": p["protocol"],
                          "server": p["server"], "security": p["security"],
                          "transport": transport}
            except ValueError as e:
                err = _tr('msg.modules.proxy.manager.could_not_parse_the_link', p0=f'{e}')
        ours = self._ours_alive
        running = ours or bool(self._system_pids())
        _dom, _nets = self._split()
        return {
            "running": running,
            "external": running and not ours,
            "link": self.config["link"],
            "parsed": parsed,
            "lists": self.config["lists"],
            "apps": list(self.config.get("apps") or []),
            "domains": len(_dom),
            "ips": len(_nets),
            "all_lists": [i["name"] for i in domains.list_info()],
            "core": {"present": SINGBOX_EXE.exists(), "version": self.core_version()},
            "autostart": self.config["autostart"],
            "mode": self.config.get("mode", "pac"),
            "socks_port": int(self.config["socks_port"]),
            "needs_admin": self.needs_admin,
            "error": self._error or err,
        }
