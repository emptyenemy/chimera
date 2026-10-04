"""Картинки для README: экран автонастройки с итогом подбора — ru и en, тёмная и светлая тема.

Стенд тот же, что у tools/smoke_autotune.py: настоящий Api и смоделированная сеть, поэтому
на снимках нет ничего с компьютера, где их снимали. Окно программы не открывается —
headless Edge. Каждый снимок — в своём процессе: пути данных модули запоминают при импорте.

    python tools/readme_shots.py      — перезаписывает assets/screens/autotune-<язык>-<тема>.png
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "screens"
SHOTS = [(lang, theme) for lang in ("ru", "en") for theme in ("dark", "light")]


def next_version() -> str:
    """Версия из самых свежих заметок к выпуску: в исходниках VERSION — "dev"."""
    sys.path.insert(0, str(ROOT))
    from modules.version import parse
    names = [p.name.removesuffix(".ru.md") for p in (ROOT / "release-notes").glob("*.ru.md")]
    return max(names, key=parse)


def one(lang: str, theme: str, version: str) -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    import smoke_autotune
    with smoke_autotune.stand(lang, theme) as url:
        from ui import api as api_mod
        api_mod.VERSION = version
        smoke_autotune.run_script(url, ROOT / "tools/readme_shots.js", OUT / f"autotune-{lang}-{theme}.png")


def main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "--one":
        one(*sys.argv[2:])
        return
    OUT.mkdir(parents=True, exist_ok=True)
    version = next_version()
    for lang, theme in SHOTS:
        subprocess.run([sys.executable, __file__, "--one", lang, theme, version], check=True)
        print(f"записано: assets/screens/autotune-{lang}-{theme}.png")


if __name__ == "__main__":
    main()
