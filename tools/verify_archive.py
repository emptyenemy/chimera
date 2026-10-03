"""Validate and test the extracted Windows archive, rather than the build folder."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract(archive, destination, flavor):
    folder = "Chimera" if flavor == "qt" else f"Chimera-{flavor}"
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination / folder):
                raise ValueError(f"Archive entry outside {folder}: {entry.filename}")
        zipped.extractall(destination)
    app = destination / folder
    manifest = app / "manifest.txt"
    recorded = set(manifest.read_text(encoding="utf-8").splitlines())
    actual = {p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file() and p != manifest}
    if actual != recorded:
        raise ValueError(f"Manifest mismatch: missing {sorted(recorded - actual)}, unlisted {sorted(actual - recorded)}")
    required = (
        "Chimera.exe", "flavor.json", "versions.json", "AGENTS.md", "skills/chimera/SKILL.md",
        "ui/web-next/index.html", "modules/locales/ru.json", "modules/locales/en.json",
        "bin/sing-box/sing-box.exe", "bin/sing-box/libcronet.dll", "bin/zapret-win-bundle/zapret-winws/winws2.exe",
        "bin/zapret-win-bundle/zapret-winws/WinDivert.dll", "bin/zapret-win-bundle/zapret-winws/WinDivert64.sys",
    )
    if flavor != "qt":
        required += ("bin/webview2/msedgewebview2.exe", "bin/webview2/msedge.dll",
                     "bin/webview2/icudtl.dat", "bin/webview2/resources.pak",
                     "bin/webview2/chimera-runtime.json", "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
                     "webview/lib/Microsoft.Web.WebView2.Core.dll",
                     "clr_loader/ffi/dlls/amd64/ClrLoader.dll", "pythonnet/runtime/Python.Runtime.dll")
    missing = [name for name in required if not (app / name).is_file()]
    if missing:
        raise ValueError(f"Archive is incomplete: {missing}")
    if json.loads((app / "flavor.json").read_text(encoding="utf-8")) != {"flavor": flavor}:
        raise ValueError("Archive flavor mismatch")
    for directory, pattern in (("ui/web-next/assets", "*.js"), ("lists", "*.txt"), ("strategies/assets", "*.bin")):
        if not any((app / directory).glob(pattern)):
            raise ValueError(f"Archive has no {directory}/{pattern}")
    return app


def verify(archive, flavor, version, full=False, screenshot=None):
    with tempfile.TemporaryDirectory(prefix="chimera-archive Кириллица ") as temporary:
        if not Path(temporary).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ValueError("Archive check folder outside temp")
        app = extract(archive, temporary, flavor)
        env = {**os.environ, "CHIMERA_DATA": str(Path(temporary) / "data"), "CHIMERA_SMOKE": "1"}
        result = subprocess.run([str(app / "Chimera.exe"), "agent-info", "--json"], cwd=app, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Archive CLI failed with code {result.returncode}: {result.stderr[:2000]}")
        payload = json.loads(result.stdout)
        if not payload.get("ok") or payload["data"]["program"]["version"] != version:
            raise ValueError("Archive executable version mismatch")
        print(f"Archive structure, manifest and CLI verified: {flavor} {version}", flush=True)
        shell = [sys.executable, str(ROOT / "tools/smoke_launch.py"), str(app), "--flavor", flavor]
        if screenshot is not None:
            shell.extend(["--screenshot", str(screenshot)])
        subprocess.run(shell, cwd=ROOT, check=True)
        if flavor == "lite":
            fallback = [*shell, "--no-browser"]
            if screenshot is not None:
                fallback[fallback.index("--screenshot") + 1] = str(screenshot.with_stem(screenshot.stem + "-fallback"))
            subprocess.run(fallback, cwd=ROOT, check=True)
        command = [sys.executable, str(ROOT / "tools/smoke_build.py"), str(app), "--flavor", flavor]
        if full:
            command.append("--full")
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--flavor", required=True, choices=("qt", "webview", "lite"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--full", action="store_true", help="System changes; disposable Windows runner only")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    verify(args.archive.resolve(), args.flavor, args.version, args.full, args.screenshot)
