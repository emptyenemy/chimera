"""Общие списки доменов (lists/*.txt) — единый источник для всех модулей.

Один файл = один сервис (openai.txt, discord.txt, ...), по домену на строку,
# — комментарий. Эти же списки дальше пойдут в hostlist'ы zapret и VPN-правила.
"""

import re
from pathlib import Path

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
    path.write_text(text, encoding="utf-8")
    return {"name": name, "count": len(load_list(name))}


def create_list(name: str) -> dict:
    path = _safe_path(name)
    if path.exists():
        raise ValueError(f"Список {name!r} уже существует")
    path.write_text(f"# {name}\n", encoding="utf-8")
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
