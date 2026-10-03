"""Провайдеры для DNS и hosts в одном месте: вкладка «Провайдеры» и `chimera providers`.

Вкладки DNS и Hosts только выбирают из них. Сами записи живут как раньше:
DNS-провайдеры — dns_providers (встроенные и свои), готовые наборы адресов —
hosts.static_providers. Скрытые встроенные (их нельзя удалить: вернутся с
обновлением) перечислены в config.json, ключ providers_hidden.
"""

from modules import appconfig, dns_providers
from modules.errors import ChimeraValueError
from modules.hosts import static_providers

HIDDEN_KEY = "providers_hidden"


def hidden_ids() -> set[str]:
    return set(appconfig.load().get(HIDDEN_KEY) or [])


def listing(assignments: dict) -> list[dict]:
    """Все провайдеры, включая скрытые, с тем, где они используются."""
    hidden = hidden_ids()
    items = [{**p, "kind": "dns"} for p in dns_providers.load_all()]
    items += [{**p, "kind": "static", "builtin": True} for p in static_providers.providers()]
    for p in items:
        p["hidden"] = bool(p.get("builtin")) and p["id"] in hidden
        bound = assignments.get(p["id"])
        p["hosts_lists"] = len(bound) if isinstance(bound, list) else (1 if bound else 0)
    return items


def set_hidden(provider_id: str, hidden: bool, assignments: dict) -> list[str]:
    builtin = {p["id"] for p in listing({}) if p.get("builtin")}
    if provider_id not in builtin:
        raise ChimeraValueError('err.dns_providers.only_built_in_providers_can_be_hidden')
    if hidden and assignments.get(provider_id):
        # записи в hosts остались бы, а провайдер пропал бы из виду
        raise ChimeraValueError('err.hosts.manager.unassign_before_hiding')
    current = [i for i in hidden_ids() if i in builtin and i != provider_id]
    value = sorted(current + [provider_id]) if hidden else sorted(current)
    appconfig.set_value(HIDDEN_KEY, value)
    return value
