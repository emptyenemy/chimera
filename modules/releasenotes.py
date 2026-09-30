"""Release notes bundled with the app and used when publishing a GitHub release."""

from pathlib import Path

from modules import i18n, paths
from modules.version import VERSION, parse

ROOT = paths.APP_DIR / "release-notes"


def read(version=VERSION, lang=None, root=ROOT):
    root = Path(root)
    lang = lang if lang in i18n.LANGS else i18n.current_lang()
    if version == "dev":
        versions = [p.name.removesuffix(".ru.md") for p in root.glob("*.ru.md")]
        version = max((v for v in versions if parse(v)), key=parse, default="dev")
    if parse(version) is None:
        return {"version": version, "notes": "", "url": None}
    version = version.removeprefix("v")
    notes = ""
    for selection in dict.fromkeys((lang, "ru")):
        path = root / f"{version}.{selection}.md"
        if path.is_file():
            notes = path.read_text(encoding="utf-8").strip()
            break
    return {"version": version, "notes": notes,
            "url": f"https://github.com/emptyenemy/chimera/releases/tag/v{version}"}
