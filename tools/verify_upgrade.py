"""Check an actual 1.0.0 -> new Qt archive upgrade inside a temporary directory."""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300, **kwargs)


def verify(archive, version):
    if sys.platform != "win32":
        raise RuntimeError("The upgrade check requires Windows")
    archive = Path(archive).resolve()
    with tempfile.TemporaryDirectory(prefix="chimera-upgrade-") as tmp:
        work = Path(tmp).resolve()
        assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
        source = work / "old_selfupdate.py"
        source.write_bytes(subprocess.check_output(["git", "show", "v1.0.0:modules/selfupdate.py"], cwd=ROOT))
        spec = importlib.util.spec_from_file_location("old_selfupdate", source)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)

        old_zip = work / "Chimera-1.0.0-win64.zip"
        run(["gh", "release", "download", "v1.0.0", "--repo", "emptyenemy/chimera",
             "--pattern", old_zip.name, "--dir", str(work)])
        installed = old.stage(old_zip, work / "installed")
        assert "1.0.0" in run([str(installed / "Chimera.exe"), "--version"]).stdout

        private = {"config.json": b'{"close_to_tray":true,"theme":"light"}\n',
                   "lists/upgrade-check.txt": b"keep.example.org\n",
                   "data/upgrade-check.json": b'{"preserve":true}\n',
                   "personal-note.txt": b"user file\n"}
        for relative, data in private.items():
            path = installed / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        with archive.open("rb") as archive_file:
            digest = hashlib.file_digest(archive_file, "sha256").hexdigest()
        release = {"tag_name": f"v{version}", "assets": [{"name": archive.name,
                   "digest": f"sha256:{digest}", "size": archive.stat().st_size,
                   "browser_download_url": archive.as_uri()}]}
        from modules import paths
        original = paths.IS_FROZEN, paths.APP_DIR
        paths.IS_FROZEN, paths.APP_DIR = True, installed
        try:
            found = old.check(current="1.0.0", fetch=lambda url: [release])
        finally:
            paths.IS_FROZEN, paths.APP_DIR = original
        assert found["latest"] == version and found["installable"], found
        downloaded = old.download(found["asset"], work / "download")
        staged = old.stage(downloaded, work / "staged")
        assert installed.resolve().is_relative_to(work)
        assert staged.resolve().parent.is_relative_to(work)
        script = old.write_script(installed, staged, 2147483647, False, False,
                                  script=work / "apply.cmd", log=work / "update.log",
                                  rollback=work / "rollback")
        run(["cmd", "/c", str(script)], cwd=work)
        log = (work / "update.log").read_text(encoding="utf-8", errors="replace")
        assert "готово" in log and "откат" not in log, log[-2000:]
        assert version in run([str(installed / "Chimera.exe"), "--version"]).stdout
        for relative, data in private.items():
            assert (installed / relative).read_bytes() == data, relative
        notes = installed / "release-notes" / f"{version}.ru.md"
        assert notes.is_file() and "Chimera " + version in notes.read_text(encoding="utf-8")
        assert (work / "rollback" / "Chimera.exe").is_file()
        print(json.dumps({"from": "1.0.0", "to": version, "ok": True,
                          "user_files_preserved": list(private), "rollback_saved": True}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    verify(args.archive, args.version)
