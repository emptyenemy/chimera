"""Compose a bilingual GitHub release body from the bundled release notes."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules.version import parse  # noqa: E402


def render(version, checksums="", root=ROOT / "release-notes"):
    if parse(version) is None:
        raise ValueError("Invalid release version")
    version = version.removeprefix("v")
    parts = []
    for lang in ("ru", "en"):
        notes = (root / f"{version}.{lang}.md").read_text(encoding="utf-8").strip()
        if not notes:
            raise ValueError("Empty release notes")
        parts.append(f"<!-- chimera:{lang} -->\n{notes}\n<!-- /chimera:{lang} -->")
    if checksums.strip():
        parts.append("## SHA256\n\n```text\n" + checksums.strip() + "\n```")
    return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checksums = args.checksums.read_text(encoding="utf-8") if args.checksums else ""
    args.output.write_text(render(args.version, checksums), encoding="utf-8", newline="\n")
