"""Паритет интерфейса и командной строки: любое действие окна доступно командой chimera.

Тест обходит все публичные методы ui/api.py и все вызовы api("…") во фронте. Метод, которого
нет в таблице команд (modules/cli/registry.py) и в списке исключений с причиной, роняет
тест: так паритет сохранится, когда в Api добавят новый метод.
"""

import inspect
import re
from pathlib import Path

from modules import control
from modules.cli import registry
from ui.api import Api

ROOT = Path(__file__).resolve().parent.parent
API_METHODS = sorted(n for n, _f in inspect.getmembers(Api, inspect.isfunction) if not n.startswith("_"))
MAPPED = registry.allowed_methods()


def test_every_api_method_has_a_command_or_a_documented_exclusion():
    missing = [m for m in API_METHODS if m not in MAPPED and m not in registry.EXCLUDED]
    assert not missing, (
        f"методы Api без команды chimera: {missing}. Добавьте действие в modules/cli/registry.py "
        "или запишите метод в EXCLUDED с причиной.")


def test_exclusions_are_real_methods_with_reasons():
    for name, why in registry.EXCLUDED.items():
        assert name in API_METHODS, f"{name} в EXCLUDED, но такого метода нет в Api"
        assert len(why.strip()) > 10, f"у исключения {name} нет причины"


def test_registered_methods_exist_in_api():
    unknown = sorted(m for m in MAPPED if m not in API_METHODS)
    assert not unknown, f"в таблице команд методы, которых нет в Api: {unknown}"


def test_method_is_not_both_mapped_and_excluded():
    assert not (set(MAPPED) & set(registry.EXCLUDED))


def _frontend_calls(files) -> set[str]:
    # api("метод", …) и типизированный api<Тип>("метод", …) в новом фронте на TypeScript
    pattern = re.compile(r'\bapi(?:<[^()]*>)?\(\s*["\']([a-z_0-9]+)["\']')
    calls = set()
    for f in files:
        calls.update(pattern.findall(f.read_text(encoding="utf-8")))
    return calls


def test_every_call_of_the_new_frontend_is_covered():
    src = ROOT / "frontend" / "src"
    files = [*src.rglob("*.ts"), *src.rglob("*.tsx")]
    assert files, "нет исходников нового фронта: frontend/src"
    calls = _frontend_calls(files)
    assert "winws_start" in calls, "в новом фронте не нашлось вызовов api(...): изменился способ вызова?"
    uncovered = sorted(c for c in calls if c not in MAPPED and c not in registry.EXCLUDED)
    assert not uncovered, f"действия нового окна без команды: {uncovered}"


def test_channel_allows_exactly_what_the_table_maps():
    assert control.ALLOWED_METHODS == registry.allowed_methods()


def test_every_action_is_documented():
    for a in registry.ACTIONS:
        assert a.summary.strip() and a.ui.strip(), a.command
        assert a.examples, f"у {a.command} нет примеров"
        assert a.level in registry.LEVEL_TITLES, a.command
        assert a.group in registry.GROUPS, a.command
        assert a.method or a.handler, f"{a.command}: нет ни метода, ни обработчика"


def test_actions_with_handlers_have_them():
    from modules.cli import commands
    missing = [a.command for a in registry.ACTIONS if a.handler and a.handler not in commands.HANDLERS]
    assert not missing, missing


def test_dangerous_methods_are_system_level():
    system = {"winws_start", "winws_stop", "hosts_set_enabled", "hosts_set_assignments", "dns_set", "dns_reset",
              "proxy_start", "proxy_stop", "proxy_set_mode", "selfupdate_install", "autostart_set",
              "game_filter_set", "ipset_update", "upstream_update"}
    for method in system:
        levels = {a.level for a in registry.ACTIONS if a.method == method or method in a.methods}
        assert levels and registry.SYSTEM in levels, f"{method} должен быть уровня system"


def test_state_readers_are_read_level():
    for method in ("winws_state", "proxy_state", "tg_state", "hosts_state", "dns_state", "lists_all",
                   "config_read", "selfupdate_state", "filters_state", "app_info"):
        acts = [a for a in registry.ACTIONS if a.method == method]
        assert all(a.level == registry.READ for a in acts), method
