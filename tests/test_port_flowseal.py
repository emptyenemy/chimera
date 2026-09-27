"""«Золотой» тест генератора стратегий: перепорт .bat из submodule
upstream/zapret-discord-youtube во временную папку должен дать БАЙТ-В-БАЙТ те
же strategies/*.txt, что уже лежат в репозитории. Если это не так — либо
кто-то поправил сгенерированный .txt руками (и правка потеряется при
следующем перепорте), либо генератор с тех пор разошёлся с исходником.

Реальная strategies/ не трогается — main()/sync_resources() пишут только в
tmp_path (см. параметр `out`, добавленный в tools/port_flowseal.py). Если
сабмодуль zapret-discord-youtube не инициализирован — тест скипается.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = ROOT / "strategies"
SRC = ROOT / "upstream" / "zapret-discord-youtube"

spec = importlib.util.spec_from_file_location("port_flowseal", ROOT / "tools" / "port_flowseal.py")
port_flowseal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port_flowseal)

pytestmark = pytest.mark.skipif(
    not (SRC / "general.bat").exists(),
    reason="сабмодуль upstream/zapret-discord-youtube не инициализирован",
)


def test_generated_strategy_ids_match_stratsdict():
    """STRATS — единственный источник того, какие id генератор производит."""
    generated_ids = {meta[0] for meta in port_flowseal.STRATS.values()}
    on_disk = {p.stem for p in STRATEGIES_DIR.glob("*.txt")}
    # default.txt — ручная стратегия, генератором не производится и не трогается
    assert "default" in on_disk
    assert "default" not in generated_ids
    assert generated_ids == on_disk - {"default"}


def test_report_matches_current_strategies(tmp_path):
    port_flowseal.main(src=SRC, out=tmp_path)

    generated = sorted(p.name for p in tmp_path.glob("*.txt"))
    expected = sorted(meta[0] + ".txt" for meta in port_flowseal.STRATS.values())
    assert generated == expected

    mismatches = []
    for name in expected:
        want = (STRATEGIES_DIR / name).read_text(encoding="utf-8")
        got = (tmp_path / name).read_text(encoding="utf-8")
        if want != got:
            mismatches.append(name)
    assert not mismatches, f"перепорт разошёлся с strategies/ для: {mismatches}"


def test_default_strategy_not_touched_by_generator(tmp_path):
    """Ручная стратегия default.txt не должна появляться в выходной папке генератора."""
    port_flowseal.main(src=SRC, out=tmp_path)
    assert not (tmp_path / "default.txt").exists()
