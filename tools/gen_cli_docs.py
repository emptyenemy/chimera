"""Генерирует docs/CLI.md из таблицы команд (modules/cli/registry.py).

    python tools/gen_cli_docs.py           # записать docs/CLI.md
    python tools/gen_cli_docs.py --check   # только проверить, что файл актуален (код 1, если нет)

Документация внутри программы (`chimera docs`, `chimera agent-info`) строится из того же
источника при каждом запуске и отдельной генерации не требует; перегенерировать нужно
только этот файл. Тест tests/test_cli_docs.py падает, если он отстал от кода.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.cli import docs  # noqa: E402

OUT = ROOT / "docs" / "CLI.md"


def main(argv: list[str]) -> int:
    text = docs.cli_md()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if current != text:
            print("docs/CLI.md устарел: python tools/gen_cli_docs.py")
            return 1
        print("docs/CLI.md актуален")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"записано: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
