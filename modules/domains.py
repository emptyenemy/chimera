"""Общие списки доменов и IP (lists/*.txt) — единый источник для всех модулей.

Один файл = один сервис (openai.txt, discord.txt, ...), по записи на строку,
# — комментарий. В одном файле можно мешать домены и IP/подсети: разделением
занимается split_entries(), а каждый потребитель уводит две половины в свой
канал (hostlist vs ipset у zapret, domain_suffix vs ip_cidr у sing-box).
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraFileNotFoundError, ChimeraValueError
from modules.fileutil import replace_file

import hashlib
import ipaddress
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from modules.fileutil import atomic_write_text

LISTS_DIR = Path(__file__).parent.parent / "lists"

# имя списка = имя файла без .txt; разрешаем только безопасные символы (без путей)
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Что записали мы сами: имя (без учёта регистра) -> (хэш содержимого, время); хэш None — файл удалили
# мы. По этому наблюдатель за файлами (modules/filewatch.py) отличает наши записи от правок снаружи и
# не применяет то, что уже применено. Запись делается до самой правки файла и живёт OWN_TTL секунд:
# если наблюдатель до файла не дошёл (следит служба, запись из командной строки), запись протухает,
# иначе откат файла к старому содержимому считался бы «нашим».
OWN_TTL = 10.0
_clock = time.monotonic
_own: dict[str, tuple[str | None, float]] = {}


def content_hash(data: bytes) -> str:
    """Хэш содержимого без учёта переводов строк: CRLF и LF одного текста не различаются."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


@contextmanager
def _own_change(changes):
    previous, marked = {}, {}
    for name, digest in changes:
        key = name.strip().casefold()
        if key not in previous:
            previous[key] = _own.get(key)
        marked[key] = (digest, _clock())
        _own[key] = marked[key]
    try:
        yield
    except Exception:
        for key, marker in marked.items():
            if _own.get(key) is marker:
                if previous[key] is None:
                    _own.pop(key, None)
                else:
                    _own[key] = previous[key]
        raise


def own_written(name: str) -> tuple[bool, str | None]:
    """(писали ли мы этот список недавно, хэш записанного; None — удалили мы)."""
    key = name.strip().casefold()
    entry = _own.get(key)
    if entry and _clock() - entry[1] > OWN_TTL:
        del _own[key]
        entry = None
    return (True, entry[0]) if entry else (False, None)


def own_forget(name: str) -> None:
    _own.pop(name.strip().casefold(), None)


def own_prune() -> None:
    """Выбрасывает протухшие записи."""
    for name in list(_own):
        own_written(name)


def _safe_path(name: str) -> Path:
    name = name.strip()
    if not NAME_RE.match(name):
        raise ChimeraValueError('err.domains.list_names_may_contain_only_latin_letters_digits')
    return LISTS_DIR / f"{name}.txt"


def available_lists() -> list[str]:
    return sorted(p.stem for p in LISTS_DIR.glob("*.txt") if p.is_file())


def list_info() -> list[dict]:
    """Имена списков и число доменов в каждом — для вывода в UI."""
    return [{"name": name, "count": len(load_list(name))} for name in available_lists() if NAME_RE.fullmatch(name)]


def list_index() -> list[dict]:
    """Списки вместе с записями — для поиска по ним в окне (списки маленькие, сотни строк)."""
    result = []
    for name in available_lists():
        if NAME_RE.fullmatch(name):
            entries = load_list(name)
            result.append({"name": name, "count": len(entries), "entries": entries})
    return result


def read_raw(name: str) -> str:
    path = _safe_path(name)
    if not path.exists():
        raise ChimeraFileNotFoundError('err.domains.list_was_not_found', p0=f'{name!r}')
    return path.read_text(encoding="utf-8")


def save_raw(name: str, content: str) -> dict:
    path = _safe_path(name)
    text = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    with _own_change([(name, content_hash(text.encode("utf-8")))]):
        atomic_write_text(path, text)
    return {"name": name, "count": len(load_list(name))}


def create_list(name: str) -> dict:
    path = _safe_path(name)
    if path.exists():
        raise ChimeraValueError('err.domains.list_already_exists', p0=f'{name!r}')
    text = f"# {name}\n"
    with _own_change([(name, content_hash(text.encode("utf-8")))]):
        atomic_write_text(path, text)
    return {"name": name, "count": 0}


def delete_list(name: str) -> None:
    path = _safe_path(name)
    if path.exists():
        with _own_change([(name, None)]):
            path.unlink()


def rename_list(old: str, new: str) -> dict:
    old_path = _safe_path(old)
    new_path = _safe_path(new)
    if not old_path.exists():
        raise ChimeraFileNotFoundError('err.domains.list_was_not_found', p0=f'{old!r}')
    if old != new and new_path.exists():
        raise ChimeraValueError('err.domains.list_already_exists', p0=f'{new!r}')
    digest = content_hash(old_path.read_bytes())
    with _own_change([(old, None), (new, digest)]):
        replace_file(old_path, new_path)   # список читают окно, служба и наблюдатель — ждём, пока отпустят
    return {"name": new, "count": len(load_list(new))}


def load_list(name: str) -> list[str]:
    path = LISTS_DIR / f"{name}.txt"
    if not path.exists():
        raise ChimeraFileNotFoundError('err.domains.domain_list_was_not_found_in', p0=f'{name!r}', p1=LISTS_DIR)
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


# --- проверка файла списка --------------------------------------------------------

# метка домена: буквы (в том числе не латинские), цифры, _ и дефис, не с дефиса и не на дефис
_LABEL_RE = re.compile(r"(?!-)[\w-]{1,63}(?<!-)")
_IP_LIKE_RE = re.compile(r"[0-9a-fA-F:.]+(/\d+)?")


def _entry_problem(entry: str) -> str | None:
    """Что не так с записью, которая не разобралась как IP/подсеть; None — это годный домен."""
    if "://" in entry:
        return _tr('msg.modules.domains.looks_like_a_url_keep_only_the_domain')
    if "*" in entry:
        return _tr('msg.modules.domains.an_asterisk_is_not_needed_example_com_also_cover')
    if re.search(r"\s", entry):
        return _tr('msg.modules.domains.whitespace_inside_the_entry')
    if _IP_LIKE_RE.fullmatch(entry) and ("/" in entry or ":" in entry or entry.rsplit(".", 1)[-1].isdigit()):
        return _tr('msg.modules.domains.looks_like_an_ip_address_or_subnet_but_cannot_be')
    if "/" in entry or ":" in entry or "@" in entry:
        return _tr('msg.modules.domains.domains_must_not_contain_paths_ports_or_credenti')
    name = entry.lstrip(".").rstrip(".")
    labels = name.split(".")
    if len(name) > 253 or not all(_LABEL_RE.fullmatch(label) for label in labels):
        return _tr('msg.modules.domains.not_a_domain_empty_parts_or_invalid_characters')
    return None


def validate_lists(name: str | None = None) -> dict:
    """Проверяет один или все списки, сохраняя ошибки отдельных файлов в общем отчёте."""
    results = []
    for item in [name] if name is not None else available_lists():
        try:
            results.append(validate_list(item))
        except (FileNotFoundError, ValueError) as error:
            if name is not None:
                raise
            results.append({"name": item, "entries": 0, "domains": 0, "networks": 0,
                            "warnings": [], "ok": False,
                            "errors": [{"line": None, "entry": "", "problem": str(error)}]})
    return {"lists": results}


def validate_list(name: str) -> dict:
    """Проверяет файл списка, ничего не меняя: кодировка, синтаксис записей, дубликаты.

    Ошибки (errors) — записи, которые потребители прочтут неправильно; предупреждения
    (warnings) — дубликаты, которые схлопываются сами. Номера строк с единицы."""
    path = _safe_path(name)
    if not path.exists():
        raise ChimeraFileNotFoundError('err.domains.list_was_not_found', p0=f'{name!r}')
    errors: list[dict] = []
    warnings: list[dict] = []
    result = {"name": name.strip(), "entries": 0, "domains": 0, "networks": 0,
              "errors": errors, "warnings": warnings, "ok": True}
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        errors.append({"line": None, "entry": "", "problem": _tr('msg.modules.domains.the_file_is_not_utf_8_first_invalid_byte', p0=f'{e.start}')})
        result["ok"] = False
        return result
    if text.startswith("﻿"):
        errors.append({"line": 1, "entry": "", "problem": _tr('msg.modules.domains.bom_at_the_beginning_of_the_file_save_as_utf_8_w')})
        text = text[1:]
    seen: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        result["entries"] += 1
        normalized = normalize_entry(entry)
        doms, nets = split_entries([entry])
        if not nets:
            problem = _entry_problem(normalized)
            if problem:
                errors.append({"line": number, "entry": entry, "problem": problem})
                continue
        if normalized != entry.lower().strip("."):
            # ссылку, www. или кириллицу программа читает сама — подсказываем, во что превратится
            warnings.append({"line": number, "entry": entry,
                             "problem": _tr('msg.modules.domains.read_as', p0=normalized)})
        key = nets[0] if nets else doms[0]
        if key in seen:
            warnings.append({"line": number, "entry": entry, "problem": _tr('msg.modules.domains.duplicate_of_the_entry_on_line', p0=f'{seen[key]}')})
            continue
        seen[key] = number
        result["networks" if nets else "domains"] += 1
    result["ok"] = not errors
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


def normalize_entry(entry: str) -> str:
    """Запись к виду, который понимают winws, sing-box и hosts: из ссылки — хост, без порта,
    пути, www., *. и точек по краям, кириллица — в punycode. IP и подсети не трогаем.
    Файл списка при этом не меняется: так читаются вставленные как есть адреса страниц."""
    entry = entry.strip()
    if not entry or as_network(entry) is not None or re.fullmatch(r"[\d.:a-fA-F]+/\d+", entry):
        return entry  # битую подсеть (10.0.0.0/33) не принимаем за адрес с путём: это ошибка записи
    if "://" in entry:
        try:
            entry = urlsplit(entry).hostname or entry
        except ValueError:
            return entry
    else:
        entry = re.split(r"[/?#]", entry, maxsplit=1)[0].rsplit("@", 1)[-1]
        if entry.count(":") == 1:
            entry = entry.split(":", 1)[0]  # домен:порт
    entry = entry.strip().strip(".").lower()
    if as_network(entry) is not None:
        return entry
    for prefix in ("*.", "www."):
        # *.example.com и www.example.com — тот же сайт: суффикс example.com покрывает поддомены
        if entry.startswith(prefix) and entry.count(".") > 1:
            entry = entry[len(prefix):]
    if not entry.isascii():
        try:
            entry = entry.encode("idna").decode("ascii")
        except UnicodeError:
            pass
    return entry


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
        entry = normalize_entry(entry)
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
