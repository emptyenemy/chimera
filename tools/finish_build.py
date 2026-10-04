"""Собрать переносимую папку после Nuitka; все пути ограничены build/."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules import dataupdate, selfupdate  # noqa: E402
from tools import fetch_bins  # noqa: E402


def data_version() -> str:
    """Версия данных сборки — дата последнего коммита (ГГГГ.ММ.ДД). Выпуски данных того же дня
    получают номер ГГГГ.ММ.ДД.N и поэтому всегда новее."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format:%Y.%m.%d"], cwd=ROOT,
                             capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out if dataupdate.version_key(out) else time.strftime("%Y.%m.%d")


def finish(flavor: str):
    if flavor not in ("qt", "webview", "lite"):
        raise ValueError(flavor)
    build = (ROOT / "build").resolve()
    source = (build / flavor / "main.dist").resolve()
    output = (build / ("Chimera" if flavor == "qt" else f"Chimera-{flavor}")).resolve()
    if not source.is_relative_to(build) or not output.is_relative_to(build):
        raise ValueError("Build paths must stay inside build/")
    if not (source / "Chimera.exe").is_file():
        raise FileNotFoundError(source / "Chimera.exe")
    required = ("bin/sing-box/sing-box.exe", "bin/sing-box/libcronet.dll", "bin/zapret-win-bundle/zapret-winws/winws2.exe",
                "bin/zapret-win-bundle/zapret-winws/WinDivert.dll", "bin/zapret-win-bundle/zapret-winws/WinDivert64.sys",
                "AGENTS.md", "skills/chimera/SKILL.md")
    missing = [relative for relative in required if not (ROOT / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing build inputs: {missing}. Run python tools/fetch_bins.py first.")
    if flavor != "qt":
        from tools.fetch_webview import validate
        validate(ROOT / "bin/webview2")
    if output.exists():
        shutil.rmtree(output)
    shutil.move(str(source), str(output))
    for relative in ("bin/sing-box", "bin/zapret-win-bundle/zapret-winws", "skills"):
        src = ROOT / relative
        if src.is_dir():
            shutil.copytree(src, output / relative)
    shutil.copy2(ROOT / "AGENTS.md", output / "AGENTS.md")
    (output / "flavor.json").write_text(json.dumps({"flavor": flavor}), encoding="utf-8")
    fetch_bins.write_versions(output / "versions.json")
    if flavor == "qt":
        fetch_bins.use_qt_runtime(output)
    else:
        shutil.copytree(ROOT / "bin/webview2", output / "bin/webview2")
    # данные, с которыми выходит сборка: от них обновление по воздуху отличает свои правки пользователя
    dataupdate.write_shipped(output, data_version())
    selfupdate.write_manifest(output)
    print(f"Done: {output / 'Chimera.exe'}")
    return output


if __name__ == "__main__":
    finish(sys.argv[1])
