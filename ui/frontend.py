"""Какой фронт показывают движки окна: прежний (ui/web) или новый (ui/web-next).

Выбор — ключ config.json `frontend`: "legacy" (по умолчанию) или "next". Новый фронт
собирается из frontend/ (`npm run build`) и в репозиторий не входит, поэтому при
"next" без сборки движок не падает: Qt и pywebview пишут причину в лог и открывают
прежний фронт, браузерный показывает страницу с подсказкой.

Пути программы (иконка окна и т. п.) от каталога фронта не зависят.
"""

from pathlib import Path

LEGACY_DIR = Path(__file__).parent / "web"
NEXT_DIR = Path(__file__).parent / "web-next"

FRONTENDS = ("legacy", "next")
DEFAULT = "legacy"

MISSING_TEXT = "Новый интерфейс не собран: выполните npm run build в папке frontend/."


def selected() -> str:
    """Что выбрано в config.json (незнакомое значение — прежний фронт)."""
    from modules import appconfig

    name = str(appconfig.load().get("frontend") or DEFAULT).lower()
    return name if name in FRONTENDS else DEFAULT


def next_built() -> bool:
    return (NEXT_DIR / "index.html").is_file()


def next_missing() -> bool:
    """Выбран новый фронт, а сборки нет."""
    return selected() == "next" and not next_built()


def web_dir() -> Path:
    """Каталог фронта для окна. Нет сборки нового — прежний, причина в лог."""
    if selected() == "next":
        if next_built():
            return NEXT_DIR
        print(MISSING_TEXT + " Открываю прежний интерфейс.")
    return LEGACY_DIR


def missing_page() -> bytes:
    """Страница браузерного движка, когда выбран новый фронт без сборки."""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Chimera</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0a0a0a;color:#fafafa;display:grid;place-items:center;height:100vh;margin:0}}
main{{max-width:34rem;padding:0 1.5rem}}code{{background:#262626;padding:.1rem .4rem;border-radius:.3rem}}p{{color:#a3a3a3}}</style></head>
<body><main><h1>Chimera</h1><p>{MISSING_TEXT}</p>
<p>Чтобы вернуть прежний интерфейс, поставьте в <code>config.json</code> <code>"frontend": "legacy"</code>.</p></main></body></html>
""".encode("utf-8")
