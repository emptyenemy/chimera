"""Генерирует docs/CLI.md (русский) и docs/en/CLI.md (английский) из таблицы команд
(modules/cli/registry.py) и каталогов текстов (modules/locales).

    python tools/gen_cli_docs.py                # записать оба файла
    python tools/gen_cli_docs.py --lang en      # только docs/en/CLI.md (ru — только docs/CLI.md)
    python tools/gen_cli_docs.py --check        # только проверить, что файлы актуальны (код 1, если нет)

Документация внутри программы (`chimera docs`, `chimera agent-info`) строится из того же
источника при каждом запуске и отдельной генерации не требует; перегенерировать нужно
только эти файлы. Тест tests/test_cli_docs.py падает, если они отстали от кода.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import i18n  # noqa: E402
from modules.cli import docs  # noqa: E402

OUT = ROOT / "docs" / "CLI.md"
OUT_BY_LANG = {"ru": OUT, "en": ROOT / "docs" / "en" / "CLI.md"}


def render(lang: str) -> str:
    with i18n.using(lang):
        return docs.cli_md()


def main(argv: list[str]) -> int:
    langs = list(OUT_BY_LANG)
    if "--lang" in argv:
        i = argv.index("--lang")
        value = argv[i + 1] if i + 1 < len(argv) else ""
        if value not in OUT_BY_LANG:
            print(f"--lang: ru или en, получено {value!r}")
            return 2
        langs = [value]
    stale = False
    for lang in langs:
        out, text = OUT_BY_LANG[lang], render(lang)
        name = out.relative_to(ROOT).as_posix()
        if "--check" in argv:
            current = out.read_text(encoding="utf-8").replace("\r\n", "\n") if out.exists() else ""
            if current != text:
                print(f"{name} устарел: python tools/gen_cli_docs.py")
                stale = True
            else:
                print(f"{name} актуален")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"записано: {name}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
