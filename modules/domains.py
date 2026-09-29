"""Общие списки доменов и IP (lists/*.txt) — единый источник для всех модулей.

Один файл = один сервис (openai.txt, discord.txt, ...), по записи на строку,
# — комментарий. В одном файле можно мешать домены и IP/подсети: разделением
занимается split_entries(), а каждый потребитель уводит две половины в свой
канал (hostlist vs ipset у zapret, domain_suffix vs ip_cidr у sing-box).
"""

import ipaddress
import re
from pathlib import Path

from modules.fileutil import atomic_write_text

LISTS_DIR = Path(__file__).parent.parent / "lists"

# имя списка = имя файла без .txt; разрешаем только безопасные символы (без путей)
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_path(name: str) -> Path:
    name = name.strip()
    if not NAME_RE.match(name):
        raise ValueError("Имя списка: только латиница, цифры, точка, дефис и подчёркивание")
    return LISTS_DIR / f"{name}.txt"


def available_lists() -> list[str]:
    return sorted(p.stem for p in LISTS_DIR.glob("*.txt"))


def list_info() -> list[dict]:
    """Имена списков и число доменов в каждом — для вывода в UI."""
    return [{"name": name, "count": len(load_list(name))} for name in available_lists()]


def read_raw(name: str) -> str:
    path = _safe_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Список {name!r} не найден")
    return path.read_text(encoding="utf-8")


def save_raw(name: str, content: str) -> dict:
    path = _safe_path(name)
    text = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    atomic_write_text(path, text)
    return {"name": name, "count": len(load_list(name))}


def create_list(name: str) -> dict:
    path = _safe_path(name)
    if path.exists():
        raise ValueError(f"Список {name!r} уже существует")
    atomic_write_text(path, f"# {name}\n")
    return {"name": name, "count": 0}


def delete_list(name: str) -> None:
    path = _safe_path(name)
    if path.exists():
        path.unlink()


def rename_list(old: str, new: str) -> dict:
    old_path = _safe_path(old)
    new_path = _safe_path(new)
    if not old_path.exists():
        raise FileNotFoundError(f"Список {old!r} не найден")
    if old != new and new_path.exists():
        raise ValueError(f"Список {new!r} уже существует")
    old_path.rename(new_path)
    return {"name": new, "count": len(load_list(new))}


def load_list(name: str) -> list[str]:
    path = LISTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Список доменов {name!r} не найден в {LISTS_DIR}")
    domains = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            domains.append(line)
    return domains


def load_lists(names: list[str]) -> list[str]:
    """Объединяет несколько списков, без дублей, с сохранением порядка."""
    seen = set()
    result = []
    for name in names:
        for domain in load_list(name):
            if domain not in seen:
                seen.add(domain)
                result.append(domain)
    return result


# --- домены vs IP ---------------------------------------------------------------


def as_network(entry: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """IP или подсеть -> сеть (голый адрес становится /32 или /128), иначе None.

    ipaddress принимает только точечную/двоеточечную запись, поэтому домен вроде
    "123.example.com" сюда не проскочит. strict=False — чтобы 10.0.0.5/24 не падал,
    а нормализовался в 10.0.0.0/24.
    """
    try:
        return ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return None


def split_entries(entries: list[str]) -> tuple[list[str], list[str]]:
    """Разделяет вперемешку заданные записи на (домены, IP-подсети).

    Домены приводятся к нижнему регистру без ведущей точки, IP — к каноничному
    CIDR. Дубли внутри каждой половины схлопываются, порядок сохраняется.
    """
    domains: list[str] = []
    nets: list[str] = []
    seen_d: set[str] = set()
    seen_n: set[str] = set()
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        net = as_network(entry)
        if net is not None:
            key = str(net)
            if key not in seen_n:
                seen_n.add(key)
                nets.append(key)
        else:
            key = entry.lower().lstrip(".")
            if key and key not in seen_d:
                seen_d.add(key)
                domains.append(key)
    return domains, nets


def split_lists(names: list[str]) -> tuple[list[str], list[str]]:
    """split_entries() поверх объединения нескольких списков."""
    return split_entries(load_lists(names))
