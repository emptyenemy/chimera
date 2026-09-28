"""Скилл для агентов (skills/chimera) и AGENTS.md: версии сходятся с программой, справочника в них нет."""

import re
from pathlib import Path

from modules import control
from modules.cli import docs

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "chimera"
# Названия вендоров и агентов записаны задом наперёд: иначе поиск следов ИИ по репозиторию находил бы
# сам этот тест. В файлах для агентов (скилл, AGENTS.md) таких названий быть не должно.
VENDORS = re.compile("|".join(w[::-1] for w in (
    "edualc", "cipohtrna", "xedoc", "ianepo", "tpgtahc", "-tpg", "inimeg", "tolipoc", "rosruc", "semreh")), re.I)


def _frontmatter() -> dict:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "у SKILL.md нет frontmatter"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in v.strip().split("."))


def test_frontmatter_has_version_and_required_protocol():
    fm = _frontmatter()
    assert fm["name"].strip() == "chimera"
    assert re.fullmatch(r"\d+\.\d+\.\d+", fm["version"].strip())
    assert fm["requires_protocol"].strip().isdigit()
    assert fm["description"].strip()


def test_cli_protocol_satisfies_skill_requirement():
    assert control.PROTOCOL >= int(_frontmatter()["requires_protocol"])


def test_skill_version_is_within_program_skill_compat():
    v = _ver(_frontmatter()["version"])
    assert _ver(docs.SKILL_COMPAT["min"]) <= v <= _ver(docs.SKILL_COMPAT["max"]), (
        "версия скилла вне диапазона skill_compat программы: поправьте SKILL_COMPAT в modules/cli/docs.py "
        "или версию скилла")


def test_changelog_mentions_current_version():
    version = _frontmatter()["version"].strip()
    changelog = (SKILL_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(version)}\b", changelog, re.M), (
        f"в skills/chimera/CHANGELOG.md нет записи о версии {version}")


def test_skill_has_no_reference_that_goes_stale():
    assert not (SKILL_DIR / "references").exists(), "справочник команд и файлов выдаёт программа (chimera docs)"
    body = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "|---" not in body, "таблиц команд в скилле быть не должно"
    assert not re.search(r"\b(data|lists|strategies|upstream|bin)/", body), "пути к файлам в скилл не пишем"
    assert not re.search(r"chimera (winws|proxy|tg|hosts|dns|lists) \w+", body), "команды с действиями в скилл не пишем"


def test_skill_points_to_program_docs():
    body = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for needed in ("chimera agent-info --json", "chimera docs", "--help", "--show-secrets", "skill_compat"):
        assert needed in body, needed
    for level in ("read", "app", "system"):
        assert f"`{level}`" in body


def test_agent_files_do_not_name_vendors():
    for path in (SKILL_DIR / "SKILL.md", SKILL_DIR / "CHANGELOG.md", ROOT / "AGENTS.md"):
        assert not VENDORS.search(path.read_text(encoding="utf-8")), path.name


def test_agents_md_is_a_short_pointer():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for needed in ("chimera agent-info --json", "chimera docs", "skills/chimera/SKILL.md"):
        assert needed in text
    assert "|---" not in text and len(text.splitlines()) < 30
