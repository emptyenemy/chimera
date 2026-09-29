"""Каталоги текстов: одинаковые наборы ключей и плейсхолдеров, ни одного неопределённого
или забытого ключа, ни одного кода ошибки вне каталога."""

import ast
import re
from pathlib import Path

import pytest

from modules import i18n
from modules.cli import docs, registry
from modules.cli import help as helptext

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("modules", "ui", "tools", "tui")
NAMESPACES = ("err.", "cli.", "docs.", "doctor.", "tray.")
FORMS = ("one", "few", "many", "other")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _split(catalog: dict) -> dict:
    """{основа ключа: {форма или '': текст}}: `x.one` и `x.few` собираются под основой `x`."""
    out = {}
    for key, text in catalog.items():
        base, _, form = key.rpartition(".")
        if base and form in FORMS:
            out.setdefault(base, {})[form] = text
        else:
            out.setdefault(key, {})[""] = text
    return out


RU, EN = i18n.catalog("ru"), i18n.catalog("en")
RU_G, EN_G = _split(RU), _split(EN)


# --- сами каталоги ----------------------------------------------------------------------------

def test_catalogs_are_flat_nonempty_strings():
    for lang, cat in (("ru", RU), ("en", EN)):
        assert cat, lang
        for key, text in cat.items():
            assert isinstance(key, str) and isinstance(text, str), (lang, key)
            assert text.strip(), f"{lang}: пустой текст у {key}"


def test_catalog_files_are_sorted_flat_json():
    """Ключи по алфавиту: правки двух авторов не спорят за место, а diff читается."""
    import json
    for lang in ("ru", "en"):
        text = (ROOT / "modules" / "locales" / f"{lang}.json").read_text(encoding="utf-8")
        keys = list(json.loads(text))
        assert keys == sorted(keys), f"{lang}.json: ключи не по алфавиту"
        assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n", f"{lang}.json: формат"


def test_both_catalogs_define_the_same_keys():
    assert set(RU_G) == set(EN_G), (
        f"только в ru: {sorted(set(RU_G) - set(EN_G))[:10]}; только в en: {sorted(set(EN_G) - set(RU_G))[:10]}")


def test_plural_groups_have_the_forms_their_language_needs():
    for lang, groups in (("ru", RU_G), ("en", EN_G)):
        required = set(i18n.PLURAL_REQUIRED[lang])
        for base, forms in groups.items():
            keys = set(forms) - {""}
            if not keys:
                continue
            assert "" not in forms, f"{lang}: {base} и с формами, и без"
            assert keys >= required, f"{lang}: у {base} нет форм {sorted(required - keys)}"
            assert keys <= set(i18n.PLURAL_CATEGORIES[lang]), f"{lang}: у {base} лишние формы"


def _params(forms: dict) -> set:
    return {p for text in forms.values() for p in PLACEHOLDER.findall(text)}


def test_placeholders_match_between_languages():
    for base in RU_G:
        ru, en = _params(RU_G[base]), _params(EN_G[base])
        assert ru == en, f"{base}: в ru {sorted(ru)}, в en {sorted(en)}"


def test_english_catalog_has_no_cyrillic():
    cyrillic = re.compile("[А-Яа-яЁё]")
    bad = [k for k, v in EN.items() if cyrillic.search(v)]
    assert not bad, f"кириллица в en: {bad[:10]}"


# --- ключи в коде -------------------------------------------------------------------------------

def _sources():
    for d in SOURCE_DIRS:
        for path in (ROOT / d).rglob("*.py"):
            if "vendor" in path.parts or "__pycache__" in path.parts:
                continue
            yield path
    yield ROOT / "main.py"


def _literal_keys():
    """Строковые литералы в коде, похожие на ключи каталога: {ключ: [файл:строка]}."""
    found = {}
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.startswith(NAMESPACES) and re.fullmatch(r"[A-Za-z0-9_.-]+", node.value)
                    and not node.value.endswith(".") and node.value.count(".") >= 1):
                found.setdefault(node.value, []).append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


LITERALS = _literal_keys()


def _defined(key: str) -> bool:
    """Ключ есть в каталоге; либо это общий префикс семейства (LazyMap(..., "cli.group"))."""
    return key in EN_G or key in EN or any(k.startswith(key + ".") for k in EN)


def test_every_key_used_in_code_is_defined():
    missing = {k: w for k, w in LITERALS.items() if not _defined(k)}
    assert not missing, f"ключи в коде, которых нет в en.json: {missing}"


def _covered_by_literal(key: str) -> bool:
    base = _split({key: ""}).popitem()[0]
    return any(base == lit or base.startswith(lit + ".") for lit in LITERALS)


def _dynamic_families() -> set:
    """Ключи, которые код собирает из таблиц (реестр команд, раскладка docs): их полноту
    проверяют тесты ниже, а не поиск литералов."""
    keys = set()
    for g in registry.GROUPS:
        keys.add(f"cli.group.{g}")
    for lvl in registry.LEVEL_TITLES:
        keys.add(f"cli.level.{lvl}")
    for m in registry.EXCLUDED:
        keys.add(f"cli.excluded.{m}")
    for a in registry.ACTIONS:
        keys |= {f"cli.cmd.{a.key}.summary", f"cli.cmd.{a.key}.ui"}
        for x in a.args:
            if not x.name.isascii():
                keys.add(f"cli.argname.{x.slug}")
            keys.add(f"cli.cmd.{a.key}.arg.{x.slug}")
    for c in helptext.EXIT_CODE_VALUES:
        keys.add(f"cli.exit.{c}")
    keys |= {f"docs.layout.{slug}" for slug, *_ in docs.LAYOUT_ITEMS}
    keys |= {f"docs.kind.{k}" for k in docs.KIND_TITLES}
    keys |= {f"docs.json.{k}" for k in docs.JSON_FORMAT}
    keys |= {f"docs.topic.{k}" for k in docs.TOPICS}
    keys |= {f"docs.flag.{k}" for k, _ in docs.GLOBAL_FLAGS}
    return keys


def test_no_unused_keys_in_catalog():
    dynamic = _dynamic_families()
    unused = sorted(k for k in EN_G if not _covered_by_literal(k) and k not in dynamic
                    and not _covered_by_extra(k))
    assert not unused, f"ключи каталога, которых нет в коде: {unused}"


def _covered_by_extra(key: str) -> bool:
    """Ключи, которые собираются по правилам, описанным в самих модулях."""
    from modules import doctor
    if key.startswith("doctor.") and key.endswith(".title"):
        return key.split(".")[1] in doctor.CHECK_IDS
    return False


def test_dynamic_families_are_complete_and_have_no_strays():
    """Для каждого ключа, который код собирает из таблицы, есть текст в обоих языках; лишних
    текстов в этих семействах нет (например, подсказка к переименованному параметру)."""
    dynamic = _dynamic_families()
    families = ("cli.group.", "cli.level.", "cli.excluded.", "cli.cmd.", "cli.argname.", "cli.exit.",
                "docs.layout.", "docs.kind.", "docs.json.", "docs.topic.", "docs.flag.")
    for key in dynamic:
        if ".arg." in key:
            # подсказка нужна не каждому параметру, но пара ru/en должна быть целой
            assert (key in EN_G) == (key in RU_G), key
        else:
            assert key in EN_G and key in RU_G, f"нет текста для {key}"
    stray = sorted(k for k in EN_G if k.startswith(families) and k not in dynamic)
    assert not stray, f"лишние ключи в каталоге: {stray}"


# --- коды ошибок ------------------------------------------------------------------------------------------

def _raised_codes():
    """Все `ChimeraError(...)` / `ChimeraValueError(...)` в коде: первый аргумент."""
    for path in _sources():
        if path.name == "errors.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                    "ChimeraError", "ChimeraValueError"):
                yield path.relative_to(ROOT), node.lineno, node.args[0] if node.args else None


def test_every_raised_chimera_error_uses_a_code_from_the_catalog():
    seen = 0
    for path, line, arg in _raised_codes():
        seen += 1
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), \
            f"{path}:{line}: код ошибки должен быть строкой-литералом"
        assert arg.value.startswith("err."), f"{path}:{line}: код {arg.value!r} не из группы err."
        assert _defined(arg.value), f"{path}:{line}: кода {arg.value!r} нет в каталоге"
        assert arg.value in RU_G, f"{path}:{line}: кода {arg.value!r} нет в ru.json"
    assert seen > 5, "не нашлось raise ChimeraError: сломан поиск?"


def test_error_codes_carry_the_params_their_text_needs():
    """Ключи err.* с плейсхолдерами: параметры, которые передаёт код, — надмножество плейсхолдеров."""
    for path in _sources():
        if path.name == "errors.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("ChimeraError", "ChimeraValueError")):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or any(k.arg is None for k in node.keywords):
                continue
            code = node.args[0].value
            given = {k.arg for k in node.keywords}
            need = _params(EN_G.get(code, {})) - {"count"} if code in EN_G else set()
            assert need <= given | ({"count"} if "count" in given else set()), \
                f"{path.relative_to(ROOT)}:{node.lineno}: {code} нужны {sorted(need)}, передано {sorted(given)}"


# --- реестр команд в обоих языках ----------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_action_is_described_in_both_languages(lang):
    with i18n.using(lang):
        for a in registry.ACTIONS:
            assert a.summary.strip() and a.summary != f"cli.cmd.{a.key}.summary", a.command
            assert a.ui.strip() and a.ui != f"cli.cmd.{a.key}.ui", a.command
            for x in a.args:
                assert x.label.strip() and not x.label.startswith("cli."), (a.command, x.name)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_generated_texts_have_no_unresolved_keys(lang):
    unresolved = re.compile(r"(?<![\w/`.-])(cli|docs|err|doctor|tray)\.[a-z_]+\.[a-z_.-]+")
    with i18n.using(lang):
        texts = [helptext.main_help(), docs.cli_md(), docs.index_text(), docs.agent_info_text()]
        texts += [helptext.group_help(g) for g in registry.GROUPS]
        texts += [helptext.action_help(a) for a in registry.ACTIONS]
        texts += [docs.topic_text(t) for t in docs.TOPICS]
    for text in texts:
        assert not unresolved.search(text), unresolved.search(text).group(0)


def test_english_generated_texts_have_no_cyrillic():
    cyrillic = re.compile("[А-Яа-яЁё]")
    with i18n.using("en"):
        texts = [helptext.main_help(), docs.cli_md(), docs.index_text(), docs.agent_info_text()]
        texts += [helptext.group_help(g) for g in registry.GROUPS]
        texts += [helptext.action_help(a) for a in registry.ACTIONS]
        texts += [docs.topic_text(t) for t in docs.TOPICS]
    for text in texts:
        m = cyrillic.search(text)
        assert not m, text[max(0, m.start() - 40): m.end() + 40]
