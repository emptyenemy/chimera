"""Версия программы: разбор, сравнение с пре-релизами, версия файла exe."""

import importlib.util
from pathlib import Path

import pytest

from modules import version

ROOT = Path(__file__).resolve().parent.parent


def test_prerelease_order():
    assert version.parse("0.3.0") > version.parse("0.3.0-beta.2") > version.parse("0.3.0-beta.1")
    # числа в пре-релизе — числами, не строками
    assert version.parse("0.3.0-beta.10") > version.parse("0.3.0-beta.2")
    assert version.parse("0.3.1-beta.1") > version.parse("0.3.0")


def test_leading_v_ignored():
    assert version.parse("v1.2.3") == version.parse("1.2.3")


def test_unparsable():
    assert version.parse("dev") is None
    assert version.parse("") is None
    assert version.parse("1.2") is None


def test_is_newer():
    # из исходников любая сборка «новее» (ставить её всё равно нельзя — решает selfupdate)
    assert version.is_newer("0.2.0", "dev") is True
    assert version.is_newer("0.2.0", "0.2.0") is False
    assert version.is_newer("0.2.0", "0.3.0-beta.1") is False
    assert version.is_newer("0.3.0", "0.3.0-beta.1") is True
    assert version.is_newer("мусор", "0.1.0") is False


def test_file_version():
    assert version.file_version("0.3.0-beta.1") == "0.3.0.1"
    assert version.file_version("0.3.0") == "0.3.0.0"
    assert version.file_version("dev") == "0.0.0.0"


def _set_version_module():
    spec = importlib.util.spec_from_file_location("set_version", ROOT / "tools" / "set_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_set_version_rejects_non_version_tag(tmp_path):
    # тег вида vtest или v1.2 не должен дать сборку с мусорной версией
    target = tmp_path / "version.py"
    target.write_text('VERSION = "dev"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="не версия"):
        _set_version_module().write("vtest", target)
    assert target.read_text(encoding="utf-8") == 'VERSION = "dev"\n'


def test_set_version_rewrites_file(tmp_path):
    mod = _set_version_module()
    target = tmp_path / "version.py"
    target.write_text((ROOT / "modules" / "version.py").read_text(encoding="utf-8"), encoding="utf-8")
    mod.write("v0.2.0", target)
    text = target.read_text(encoding="utf-8")
    assert 'VERSION = "0.2.0"' in text
    assert "def parse" in text  # остальное содержимое файла на месте
