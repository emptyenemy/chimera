"""Временная метка варианта для Nuitka; в git не входит."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "modules" / "_build_flavor.py"


def write(flavor: str) -> None:
    if flavor == "--clear":
        TARGET.unlink(missing_ok=True)
        return
    if flavor not in ("qt", "webview", "lite"):
        raise ValueError(f"unknown build flavor: {flavor}")
    TARGET.write_bytes(f'FLAVOR = "{flavor}"\r\n'.encode())


if __name__ == "__main__":
    write(sys.argv[1])
