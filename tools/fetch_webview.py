"""Fetch a pinned, portable WebView2 runtime; nothing is installed in Windows."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "154.0.4258.48"
URL = "https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/621dd012-b3d6-4b8b-a6b7-fc3938bfe9d4/Microsoft.WebView2.FixedVersionRuntime.154.0.4258.48.x64.cab"
SHA256 = "e2356456a8f02e606a731cd7646a604ed3676a9e392bd867b0207a8c3dc2d4f4"
DEST = ROOT / "bin" / "webview2"
REQUIRED = ("msedgewebview2.exe", "msedge.dll", "icudtl.dat", "resources.pak")


def validate(folder):
    folder = Path(folder)
    missing = [name for name in REQUIRED if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Incomplete portable WebView2: {missing}")
    metadata = json.loads((folder / "chimera-runtime.json").read_text(encoding="utf-8"))
    if metadata != {"version": VERSION, "sha256": SHA256}:
        raise ValueError("Portable WebView2 version mismatch")


def fetch():
    try:
        validate(DEST)
        print(f"Portable WebView2 {VERSION}: already present")
        return
    except (OSError, ValueError):
        pass
    with tempfile.TemporaryDirectory(prefix="chimera-webview-fetch-") as temporary:
        work = Path(temporary)
        archive = work / "runtime.cab"
        print(f"Downloading portable WebView2 {VERSION}", flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != SHA256:
            raise ValueError("Portable WebView2 SHA256 mismatch")
        extracted = work / "extracted"
        extracted.mkdir()
        expand = Path(os.environ["WINDIR"]) / "System32" / "expand.exe"
        subprocess.run([str(expand), str(archive), "-F:*", str(extracted)], check=True,
                       stdout=subprocess.DEVNULL, timeout=180)
        runtime = extracted / f"Microsoft.WebView2.FixedVersionRuntime.{VERSION}.x64"
        (runtime / "chimera-runtime.json").write_text(json.dumps({"version": VERSION, "sha256": SHA256}), encoding="utf-8")
        validate(runtime)
        DEST.parent.mkdir(parents=True, exist_ok=True)
        if not DEST.resolve().is_relative_to((ROOT / "bin").resolve()):
            raise ValueError("Unsafe runtime destination")
        if DEST.exists():
            shutil.rmtree(DEST)
        shutil.move(str(runtime), str(DEST))
    print("Portable WebView2 ready", flush=True)


if __name__ == "__main__":
    fetch()
