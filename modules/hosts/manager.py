"""Подмена IP в системном hosts-файле для разблокировки сервисов.

Модель простая, без наборов:
  1. выбираешь разблокирующий DNS-провайдер (xbox / comss / malw);
  2. отмечаешь списки доменов, которые хочешь разблокировать;
  3. «Применить» — домены резолвятся через провайдер, полученные IP пишутся
     ОДНИМ блоком в hosts.

Один блок = одно применённое состояние, снимается одной кнопкой. Что именно
применено (провайдер, списки, записи) хранится в state.json рядом с модулем.
"""

from modules.errors import ChimeraPermissionError, ChimeraValueError
from modules.fileutil import atomic_write_text

import ctypes
import json
from contextlib import nullcontext
import os
import re
import subprocess
from pathlib import Path

from .. import dns_providers, paths
from ..domains import split_lists
from . import static_providers
from .background import DEFAULT_OPTIONS as BACKGROUND_DEFAULTS
from .background import HostsBackground
from .resolver import resolve_domains, timed_resolve

STATE_PATH = paths.data_path("hosts.json")
paths.migrate(Path(__file__).parent / "state.json", STATE_PATH)  # разовый перенос со старого места
HOSTS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"

BEGIN_MARK = "# >>> chimera-hosts >>>"
END_MARK = "# <<< chimera-hosts <<<"
BLOCK_RE = re.compile(rf"{re.escape(BEGIN_MARK)}.*?{re.escape(END_MARK)}\r?\n?", re.S)

# по этому домену меряем работоспособность/пинг провайдеров
PING_TEST_DOMAIN = "chatgpt.com"
# короткий таймаут именно для пинга: DNS, отвечающий дольше — для нас бесполезен,
# пишем «недоступен» и не ждём
PING_TIMEOUT = 2.0


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False



def _wall_stamped(rec, key):
    """Запись с unix-меткой времени или None. Ранние версии фона писали сюда
    time.monotonic() — это секунды с загрузки ОС, и UI показывал «20 000 дней назад»."""
    if not isinstance(rec, dict) or not isinstance(rec.get(key), (int, float)) or rec[key] < 1e9:
        return None
    return rec

def _valid_background_option(key, value):
    if key in ("refresh_enabled", "check_enabled", "autoswitch_enabled"):
        return type(value) is bool
    if key in ("refresh_interval", "check_interval"):
        return type(value) is int and value > 0
    return isinstance(value, list) and all(
        isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", item) for item in value
    )


class HostsManager:
    def __init__(self, state_path: Path = STATE_PATH, hosts_path: Path = HOSTS_PATH):
        self.state_path = state_path
        self.hosts_path = hosts_path
        # один фоновый поток на автообновление/чекер/автопереключение — см. background.py.
        # Api стартует его в __init__ и гасит в shutdown(); сам по себе он не крутится.
        self.background = HostsBackground(self)

    def start_background(self) -> None:
        self.background.start()

    def stop_background(self) -> None:
        self.background.stop()

    # --- провайдеры -----------------------------------------------------------
    # dns — резолвит домены из списков на лету; static — готовый список записей
    # из файла (см. static_providers.py). Оба типа умеют обходить блокировки,
    # поэтому вкладка Hosts показывает их вместе, отличая по полю "type".

    def providers(self) -> list[dict]:
        dns = [{**p, "type": "dns"} for p in dns_providers.load_all() if p.get("unblock")]
        return dns + static_providers.providers()

    def get_provider(self, provider_id: str) -> dict:
        try:
            return {**dns_providers.get(provider_id), "type": "dns"}
        except KeyError:
            return {**static_providers.get(provider_id), "type": "static"}

    def add_provider(self, name: str, doh: str, servers) -> dict:
        # из вкладки Hosts добавляют только «обходные» провайдеры → unblock=True
        return dns_providers.add(name, servers=servers, doh=doh, unblock=True)

    def delete_provider(self, provider_id: str) -> dict:
        dns_providers.delete(provider_id)
        # снять его привязки и пересинхронизировать hosts
        st = self._load_state()
        if provider_id in st.get("assignments", {}):
            del st["assignments"][provider_id]
            self._save_state(st)
            self._sync()
        return self.state()

    def ping_one(self, provider_id: str) -> dict:
        """Один замер одного провайдера. Фронт пингует каждого независимо,
        поэтому медленный провайдер не тормозит обновление остальных.

        static-провайдеру резолвить нечего — «доступен» значит «файл сабмодуля
        на месте и парсится», без сети."""
        provider = self.get_provider(provider_id)
        if provider.get("type") == "static":
            try:
                entries = static_providers.read_entries(provider_id)
                return {"id": provider["id"], "name": provider["name"],
                        "ok": bool(entries), "ms": None, "ip": None}
            except FileNotFoundError as e:
                return {"id": provider["id"], "name": provider["name"],
                        "ok": False, "ms": None, "ip": None, "reason": str(e)}

        ips, ms = timed_resolve(
            PING_TEST_DOMAIN, provider.get("doh"), provider.get("servers"), timeout=PING_TIMEOUT
        )
        return {"id": provider["id"], "name": provider["name"],
                "ok": bool(ips), "ms": ms if ips else None, "ip": ips[0] if ips else None}

    # --- состояние ----------------------------------------------------------

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                saved = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    return saved
            except (json.JSONDecodeError, ValueError):
                pass
        # assignments: {provider_id: [list_name, ...]} — какой список через кого
        return {"assignments": {}, "entries": [], "enabled": True}

    def _save_state(self, state: dict) -> None:
        atomic_write_text(self.state_path, json.dumps(state, ensure_ascii=False, indent=2))

    def assignments(self) -> dict:
        return self._load_state().get("assignments", {})

    def restore_config(self, config: dict) -> dict:
        from modules.configbackups import normalize
        target = normalize("hosts", config)
        state = self._load_state()
        state.update(target)
        self._save_state(state)
        return self._sync()

    def set_assignments(self, mapping: dict) -> dict:
        """Сохраняет привязку списков к провайдерам (без записи в hosts).

        Эксклюзивность (один список — один провайдер) обеспечивает фронт;
        тут просто отбрасываем пустые наборы.
        """
        st = self._load_state()
        st["assignments"] = {pid: lists for pid, lists in mapping.items() if lists}
        self._save_state(st)
        return self._sync()  # сразу применяем: галочка = работает, снял = выключилось

    def state(self) -> dict:
        """Текущее состояние: привязки, число применённых записей, флаги applied/enabled,
        плюс то, что копит фоновый поток (background.py) — health чекера и последнее
        автопереключение, если оно случалось."""
        st = self._load_state()
        return {
            "applied": self._is_applied(),
            "enabled": st.get("enabled", True),
            "assignments": st.get("assignments", {}),
            "count": len(st.get("entries", [])),
            "health": st.get("health"),
            "last_switch": st.get("last_switch"),
            "background": self.background_options(),
        }

    def set_enabled(self, value: bool) -> dict:
        """Общий выключатель hosts-разблокировки. OFF снимает блок из hosts, но
        привязки (какой список через кого) сохраняет — ON переприменяет их разом."""
        st = self._load_state()
        st["enabled"] = bool(value)
        self._save_state(st)
        return self._sync()

    # --- настройки фонового потока (data/hosts.json, ключ "background") ------

    def background_options(self) -> dict:
        st = self._load_state()
        saved = st.get("background")
        saved = saved if isinstance(saved, dict) else {}
        return {key: (saved[key] if key in saved and _valid_background_option(key, saved[key])
                      else value.copy() if isinstance(value, list) else value)
                for key, value in BACKGROUND_DEFAULTS.items()}

    def set_background(self, options: dict) -> dict:
        """Сохраняет настройки автообновления/чекера/автопереключения.
        Неизвестные ключи молча отбрасываются — фронт шлёт только то, что знает."""
        if options is not None and not isinstance(options, dict):
            raise ChimeraValueError('err.hosts.manager.background_options_must_be_object')
        patch = {key: value for key, value in (options or {}).items() if key in BACKGROUND_DEFAULTS}
        for key, value in patch.items():
            if not _valid_background_option(key, value):
                raise ChimeraValueError('err.hosts.manager.invalid_background_option', p0=key)
        current = self.background_options()
        current.update(patch)
        st = self._load_state()
        st["background"] = current
        self._save_state(st)
        return current

    # --- hosts-файл ---------------------------------------------------------

    def _read_hosts(self) -> str:
        with open(self.hosts_path, encoding="utf-8", errors="replace", newline="") as file:
            return file.read()

    def _write_hosts(self, text: str) -> None:
        with open(self.hosts_path, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)

    def _is_applied(self) -> bool:
        return self.hosts_path.exists() and BEGIN_MARK in self._read_hosts()

    def _write_block(self, groups: list[tuple[str, list[dict]]]) -> None:
        """Пишет один блок, сгруппированный по провайдерам (подзаголовок на группу)."""
        text = self._read_hosts()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = [BEGIN_MARK]
        for provider_name, entries in groups:
            lines.append(f"# {provider_name}")
            lines += [f"{e['ip']} {e['host']}" for e in entries]
        lines.append(END_MARK)
        block = newline.join(lines) + newline
        match = BLOCK_RE.search(text)
        if match:
            text = text[:match.start()] + block + text[match.end():]
        else:
            text += ("" if text.endswith(("\n", "\r")) else newline) + newline + block
        self._write_hosts(text)

    # --- синхронизация hosts с привязками -----------------------------------

    def resync(self) -> dict:
        """Переприменяет привязки: резолвит заново и переписывает блок. Нужен, когда
        поменялось содержимое списка, а не сама привязка (set_assignments и так синкает)."""
        return self._sync()

    def _sync(self, expected_state=None, mutation_lock=None) -> dict:
        """Приводит hosts в соответствие с текущими привязками.

        Есть привязки и разблокировка включена → резолвим и пишем блок.
        Пусто или выключено общим тумблером → убираем блок (привязки в state остаются).
        Вызывается на каждое изменение: hosts всегда отражает галочки в UI.
        """
        st = self._load_state()
        plan = ({pid: lists for pid, lists in st.get("assignments", {}).items() if lists}
                if st.get("enabled", True) else {})

        if not plan:
            with mutation_lock or nullcontext():
                if expected_state is not None and not self.background.can_apply():
                    return self.state()
                if expected_state is not None and not self.background.same_state(expected_state, self._load_state()):
                    return self.state()
                if self._is_applied():
                    if not is_admin():
                        raise ChimeraPermissionError('err.hosts.manager.administrator_rights_are_required_to_write_hosts')
                    self._write_hosts(BLOCK_RE.sub("", self._read_hosts()))
                st = self._load_state()
                st["entries"] = []
                self._save_state(st)
                return self.state()

        if not is_admin():
            raise ChimeraPermissionError('err.hosts.manager.administrator_rights_are_required_to_write_hosts')
        groups, all_entries, unavailable = [], [], []
        for provider_id, lists in plan.items():
            provider = self.get_provider(provider_id)
            if provider.get("type") == "static":
                # static ничего не выбирает списками — привязка это просто «включён/нет»
                # (значение в assignments — True), записи все свои, из файла сабмодуля.
                try:
                    entries = static_providers.read_entries(provider_id)
                except FileNotFoundError as e:
                    unavailable.append(str(e))
                    continue
            else:
                # IP из списков тут молча пропускаем: hosts маппит имя -> адрес, для
                # готового адреса подменять нечего. Их обходом занимаются winws (ipset)
                # и прокси (ip_cidr).
                domains, _ = split_lists(lists)
                entries = resolve_domains(domains, provider.get("doh"), provider.get("servers"))
            entries = [dict(e) for e in entries]
            for e in entries:
                e["provider"] = provider_id
            if entries:
                groups.append((provider["name"], entries))
                all_entries.extend(entries)

        if not all_entries:
            if unavailable:
                raise ValueError("; ".join(unavailable))
            raise ChimeraValueError('err.hosts.manager.no_addresses_resolved_are_the_providers_unavaila')
        with mutation_lock or nullcontext():
            if expected_state is not None and not self.background.can_apply():
                return self.state()
            if expected_state is not None and not self.background.same_state(expected_state, self._load_state()):
                return self.state()
            self._write_block(groups)
            st = self._load_state()
            st["entries"] = all_entries
            self._save_state(st)
            return self.state()

