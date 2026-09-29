"""Единственный интерфейс: сборка frontend/ в ui/web-next/."""
from pathlib import Path

NEXT_DIR = Path(__file__).parent / "web-next"
DEFAULT = "next"
MISSING_TEXT = "Интерфейс не собран: выполните npm run build в папке frontend/."


def selected() -> str:
    return DEFAULT


def next_built() -> bool:
    return (NEXT_DIR / "index.html").is_file()


def next_missing() -> bool:
    return not next_built()


def web_dir() -> Path:
    if not next_built():
        raise FileNotFoundError(MISSING_TEXT)
    return NEXT_DIR


def missing_page() -> bytes:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Chimera</title></head>
<body><main><h1>Chimera</h1><p>{MISSING_TEXT}</p></main></body></html>""".encode()
