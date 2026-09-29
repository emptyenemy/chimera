"""Сборка нового фронта (frontend/ -> ui/web-next) лежит так, как её ждут движки окна.

Сборка в git не входит, поэтому без `npm run build` тесты пропускаются; в CI сборка идёт
до pytest.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "ui" / "web-next"

pytestmark = pytest.mark.skipif(not (BUILD / "index.html").is_file(), reason="нет сборки: npm run build в frontend/")


def _html() -> str:
    return (BUILD / "index.html").read_text(encoding="utf-8")


def test_paths_are_relative():
    # file:// в Qt и любой адрес движка браузера: пути от корня сайта там не сработают
    refs = re.findall(r'(?:src|href)="([^"]+)"', _html())
    assert refs
    assert not [r for r in refs if r.startswith("/") or r.startswith("http")], refs


def test_qwebchannel_goes_before_the_bundle():
    html = _html()
    assert "qwebchannel.js" in html and (BUILD / "qwebchannel.js").is_file()
    assert html.index("qwebchannel.js") < html.index('type="module"')


def test_every_referenced_file_exists():
    for ref in re.findall(r'(?:src|href)="\./([^"]+)"', _html()):
        assert (BUILD / ref).is_file(), ref


def test_fonts_are_reused_from_the_legacy_frontend():
    for f in (ROOT / "frontend" / "public" / "fonts").glob("*.woff2"):
        assert (BUILD / "fonts" / f.name).is_file(), f.name


def test_source_does_not_ship_in_the_build():
    assert not list(BUILD.rglob("*.tsx")) and not (BUILD / "node_modules").exists()
