"""Подмена IP в системном hosts-файле для разблокировки сервисов.

Модель простая, без наборов:
  1. выбираешь разблокирующий DNS-провайдер (xbox / comss / malw);
  2. отмечаешь списки доменов, которые хочешь разблокировать;
  3. «Применить» — домены резолвятся через провайдер, полученные IP пишутся
     ОДНИМ блоком в hosts.

Один блок = одно применённое состояние, снимается одной кнопкой. Что именно
применено (провайдер, списки, записи) хранится в state.json рядом с модулем.
"""

import ctypes
import json
import os
import re
import subprocess
from pathlib import Path

from .. import dns_providers
from ..domains import split_lists
from .resolver import resolve_domains, timed_resolve

MODULE_DIR = Path(__file__).parent
MODULE_DIR.mkdir(parents=True, exist_ok=True)  # в standalone-сборке (Nuitka) этой папки на диске нет
STATE_PATH = MODULE_DIR / "state.json"
HOSTS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"

BEGIN_MARK = "# >>> chimera-hosts >>>"
END_MARK = "# <<< chimera-hosts <<<"
BLOCK_RE = re.compile(rf"\r?\n?{re.escape(BEGIN_MARK)}.*?{re.escape(END_MARK)}\r?\n?", re.S)

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


class HostsManager:
    def __init__(self, state_path: Path = STATE_PATH, hosts_path: Path = HOSTS_PATH):
        self.state_path = state_path
        self.hosts_path = hosts_path

    # --- провайдеры (только умеющие обходить блокировки) --------------------

    def providers(self) -> list[dict]:
        return [p for p in dns_providers.load_all() if p.get("unblock")]

    def get_provider(self, provider_id: str) -> dict:
        return dns_providers.get(provider_id)

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
        поэтому медленный провайдер не тормозит обновление остальных."""
        provider = self.get_provider(provider_id)
        ips, ms = timed_resolve(
            PING_TEST_DOMAIN, provider.get("doh"), provider.get("servers"), timeout=PING_TIMEOUT
        )
        return {"id": provider["id"], "name": provider["name"],
                "ok": bool(ips), "ms": ms if ips else None, "ip": ips[0] if ips else None}

    # --- состояние ----------------------------------------------------------

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        # assignments: {provider_id: [list_name, ...]} — какой список через кого
        return {"assignments": {}, "entries": [], "enabled": True}

    def _save_state(self, state: dict) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def assignments(self) -> dict:
        return self._load_state().get("assignments", {})

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
        """Текущее состояние: привязки, число применённых записей, флаги applied/enabled."""
        st = self._load_state()
        return {
            "applied": self._is_applied(),
            "enabled": st.get("enabled", True),
            "assignments": st.get("assignments", {}),
            "count": len(st.get("entries", [])),
        }

    def set_enabled(self, value: bool) -> dict:
        """Общий выключатель hosts-разблокировки. OFF снимает блок из hosts, но
        привязки (какой список через кого) сохраняет — ON переприменяет их разом."""
        st = self._load_state()
        st["enabled"] = bool(value)
        self._save_state(st)
        return self._sync()

    # --- hosts-файл ---------------------------------------------------------

    def _read_hosts(self) -> str:
        return self.hosts_path.read_text(encoding="utf-8", errors="replace")

    def _write_hosts(self, text: str) -> None:
        self.hosts_path.write_text(text, encoding="utf-8")
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)

    def _is_applied(self) -> bool:
        return self.hosts_path.exists() and BEGIN_MARK in self._read_hosts()

    def _write_block(self, groups: list[tuple[str, list[dict]]]) -> None:
        """Пишет один блок, сгруппированный по провайдерам (подзаголовок на группу)."""
        text = BLOCK_RE.sub("\n", self._read_hosts())
        lines = [BEGIN_MARK]
        for provider_name, entries in groups:
            lines.append(f"# {provider_name}")
            lines += [f"{e['ip']} {e['host']}" for e in entries]
        lines.append(END_MARK)
        self._write_hosts(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n")

    # --- синхронизация hosts с привязками -----------------------------------

    def _sync(self) -> dict:
        """Приводит hosts в соответствие с текущими привязками.

        Есть привязки и разблокировка включена → резолвим и пишем блок.
        Пусто или выключено общим тумблером → убираем блок (привязки в state остаются).
        Вызывается на каждое изменение: hosts всегда отражает галочки в UI.
        """
        st = self._load_state()
        plan = ({pid: lists for pid, lists in st.get("assignments", {}).items() if lists}
                if st.get("enabled", True) else {})

        if not plan:
            if self._is_applied():
                if not is_admin():
                    raise PermissionError("Нужны права администратора для записи в hosts")
                self._write_hosts(BLOCK_RE.sub("\n", self._read_hosts()))
            st = self._load_state()
            st["entries"] = []
            self._save_state(st)
            return self.state()

        if not is_admin():
            raise PermissionError("Нужны права администратора для записи в hosts")
        groups, all_entries = [], []
        for provider_id, lists in plan.items():
            provider = self.get_provider(provider_id)
            # IP из списков тут молча пропускаем: hosts маппит имя -> адрес, для
            # готового адреса подменять нечего. Их обходом занимаются winws (ipset)
            # и прокси (ip_cidr).
            domains, _ = split_lists(lists)
            entries = resolve_domains(domains, provider.get("doh"), provider.get("servers"))
            for e in entries:
                e["provider"] = provider_id
            if entries:
                groups.append((provider["name"], entries))
                all_entries.extend(entries)

        if not all_entries:
            raise ValueError("Ничего не разрезолвилось — провайдеры недоступны?")
        self._write_block(groups)
        st = self._load_state()
        st["entries"] = all_entries
        self._save_state(st)
        return self.state()

