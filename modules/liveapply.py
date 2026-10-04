"""Применение изменений списков на лету: одна логика для окна, командной строки и службы.

Раньше жила в Api и потому работала только там; правку lists/*.txt на диске, сделанную
агентом или вручную, подхватывает наблюдатель (modules/filewatch.py) внутри процесса, у
которого Api может и не быть (фоновая служба). Модули передаются явно: любой владелец
процессов вызывает эти функции со своими winws, proxy и hosts.

Где модуль умеет подхватить файл сам (hostlist winws2, правила sing-box), просто
обновляем файлы; hosts пересчитываются заново. Сбой одного модуля (например, нет прав
на hosts) остальным не мешает и возвращается списком ошибок [{"module", "error"}].
"""

from collections.abc import Callable, Iterable


def apply_safely(errors: list, module: str, fn: Callable) -> None:
    try:
        fn()
    except Exception as e:
        errors.append({"module": module, "error": str(e)})


def _has(lists, name: str) -> bool:
    # имена файлов на Windows не различают регистр: YouTube.txt и youtube — один список
    return name.casefold() in {str(n).casefold() for n in lists or []}


def hosts_uses(hosts, name: str) -> bool:
    # у статического провайдера в привязке не список имён, а True
    return any(isinstance(lists, (list, tuple, set)) and _has(lists, name)
               for lists in hosts.assignments().values())


def _uses(names: Iterable[str], winws, proxy, hosts) -> tuple[bool, bool, bool]:
    names = list(names)
    return (any(_has(winws.config.get("lists"), n) for n in names),
            any(_has(proxy.config.get("lists"), n) or _has(proxy.config.get("direct_lists"), n) for n in names),
            any(hosts_uses(hosts, n) for n in names))


def consumers(names: Iterable[str], winws, proxy, hosts) -> list[str]:
    """Какие модули используют хотя бы один из списков."""
    used = _uses(names, winws, proxy, hosts)
    return [m for m, u in zip(("winws", "proxy", "hosts"), used, strict=True) if u]


def lists_changed(names: Iterable[str], winws, proxy, hosts) -> list:
    """Применяет изменившееся содержимое списков к тем, кто их использует; каждый модуль
    обновляется один раз, сколько бы списков ни изменилось. Возвращает ошибки применения."""
    errors: list = []
    use_winws, use_proxy, use_hosts = _uses(names, winws, proxy, hosts)
    if use_winws:
        apply_safely(errors, "winws", winws.refresh_user_lists)
    if use_proxy:
        apply_safely(errors, "proxy", proxy.reload_lists)
    if use_hosts:
        apply_safely(errors, "hosts", hosts.resync)
    return errors


def lists_removed(name: str, winws, proxy, hosts) -> list:
    """Список удалён (файла нет): убирает его из подключений. set_lists сверяет имена с
    существующими файлами, поэтому прокси и winws достаточно переустановить те же имена."""
    errors: list = []
    use_winws, use_proxy, use_hosts = _uses([name], winws, proxy, hosts)
    if use_proxy:
        apply_safely(errors, "proxy", lambda: proxy.set_lists(proxy.config["lists"]))
        if _has(proxy.config.get("direct_lists"), name):
            apply_safely(errors, "proxy", lambda: proxy.set_direct_lists(proxy.config["direct_lists"]))
    if use_winws:
        apply_safely(errors, "winws", lambda: winws.set_lists(winws.config["lists"]))
    if use_hosts:
        patched = {}
        for pid, lists in hosts.assignments().items():
            kept = [n for n in lists if n.casefold() != name.casefold()] if isinstance(lists, (list, tuple, set)) else lists
            if kept:
                patched[pid] = kept
        apply_safely(errors, "hosts", lambda: hosts.set_assignments(patched))
    return errors


def apply_event(kind: str, name: str, winws, proxy, hosts) -> list:
    """Событие наблюдателя: created | changed | removed."""
    if kind == "removed":
        return lists_removed(name, winws, proxy, hosts)
    return lists_changed([name], winws, proxy, hosts)
