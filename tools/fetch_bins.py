"""Бинарники для сборки: sing-box и winws2 — в bin/, как их ждёт программа.

    python tools/fetch_bins.py                 скачать то, чего нет в bin/
    python tools/fetch_bins.py --force         перекачать всё
    python tools/fetch_bins.py --versions F    записать версии git-источников в F (versions.json)
    python tools/fetch_bins.py --manifest D    записать D/manifest.txt — список файлов сборки
                                               (по нему самообновление отличает свои файлы от чужих)

Обе версии пиннуты, чтобы сборка была воспроизводимой:
  • sing-box — SINGBOX_VERSION/SINGBOX_SHA256 из modules/proxy/manager.py (та же
    версия, что качается кнопкой из UI, со сверкой SHA256);
  • zapret-win-bundle — коммит BUNDLE_COMMIT. Из бандла в сборку идёт только
    zapret-winws/ (winws2, WinDivert, lua): остальное — cygwin, blockcheck и
    сборки под другие платформы — программа не использует, а это ~58 МБ из 62.

versions.json читает modules/upstream.py в собранной программе: там нет ни
сабмодулей, ни .git, и «Источники и обновления» иначе показывали бы «—».
"""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import selfupdate, upstream  # noqa: E402
from modules.proxy.manager import SINGBOX_FILES, SINGBOX_SHA256, SINGBOX_URL  # noqa: E402

BIN = ROOT / "bin"
SINGBOX_EXE = BIN / "sing-box" / "sing-box.exe"
BUNDLE_DIR = BIN / "zapret-win-bundle"
BUNDLE_REPO = "https://github.com/bol-van/zapret-win-bundle"
# Коммит бандла, с которым собирается релиз. Обновлять вместе с сабмодулем
# upstream/zapret2 (версии winws2 и lua-движка должны совпадать).
BUNDLE_COMMIT = "6eb463a6758fb48cd101bc55dfd057e6e9d98af1"
BUNDLE_NAME = "winws-бандл (bol-van)"  # имя источника в modules/upstream.py


def check_sha(blob: bytes, sha: str) -> None:
    got = hashlib.sha256(blob).hexdigest()
    if got != sha.lower():
        raise RuntimeError(f"SHA256 не совпадает: ждали {sha}, получили {got} — файл повреждён или подменён")


def fetch_singbox(force: bool = False) -> None:
    if all((SINGBOX_EXE.parent / name).exists() for name in SINGBOX_FILES) and not force:
        print("sing-box: уже есть, пропускаю")
        return
    print("sing-box: качаю", SINGBOX_URL)
    req = urllib.request.Request(SINGBOX_URL, headers={"User-Agent": "chimera-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    check_sha(blob, SINGBOX_SHA256)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members = {n.rsplit("/", 1)[-1]: n for n in z.namelist()}
        missing = [name for name in SINGBOX_FILES if name not in members]
        if missing:
            raise RuntimeError(f"в архиве sing-box нет {', '.join(missing)}")
        SINGBOX_EXE.parent.mkdir(parents=True, exist_ok=True)
        for name in SINGBOX_FILES:
            target = SINGBOX_EXE.parent / name
            # без --force дописываем только недостающее: sing-box.exe может быть занят работающим прокси
            if force or not target.exists():
                target.write_bytes(z.read(members[name]))
    print("sing-box: готово")


def copy_winws(src_bundle: Path, dest_bundle: Path) -> None:
    """Кладёт zapret-winws/ из клона бандла в dest_bundle, заменяя прежнюю копию."""
    target = dest_bundle / "zapret-winws"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src_bundle / "zapret-winws", target, ignore=shutil.ignore_patterns(".git"))


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")


def fetch_bundle(force: bool = False) -> None:
    if (BUNDLE_DIR / "zapret-winws" / "winws2.exe").exists() and not force:
        print("zapret-winws: уже есть, пропускаю")
        return
    print(f"zapret-winws: клонирую бандл на {BUNDLE_COMMIT[:7]}")
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "bundle"
        _git("clone", "--filter=blob:none", "--no-checkout", BUNDLE_REPO, str(clone))
        _git("checkout", BUNDLE_COMMIT, cwd=clone)
        BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
        copy_winws(clone, BUNDLE_DIR)
    print("zapret-winws: готово")


QT_RUNTIME = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll")


def use_qt_runtime(build_dir: Path, qt_dir: Path | None = None) -> list[str]:
    """Кладёт в сборку msvcp140*.dll из PySide6 поверх тех, что положила Nuitka.

    Nuitka берёт C++-рантайм из своего компилятора (у VS2019 это 14.29), а Qt 6.11
    собран новее и требует 14.44+: на старой msvcp140 рендерер QtWebEngine падает
    с 0xC0000005, и окно программы остаётся пустым. DLL из рядом с exe грузится
    раньше системной, поэтому класть надо именно ту, с которой поставляется Qt.
    """
    if qt_dir is None:
        import PySide6
        qt_dir = Path(PySide6.__file__).parent
    copied = []
    for name in QT_RUNTIME:
        src = qt_dir / name
        if src.exists():
            shutil.copy2(src, build_dir / name)
            copied.append(name)
    return copied


def write_versions(out: Path) -> dict:
    """Версии git-источников на момент сборки — для «Источников» в собранной программе."""
    data = {}
    for src in upstream._SOURCES:
        if src["kind"] not in ("tag", "commit"):
            continue
        # бандл в сборке — пиннутый коммит, а не то, что случайно лежит в bin/ у сборщика
        data[src["path"]] = BUNDLE_COMMIT[:7] if src["path"] == "bin/zapret-win-bundle" else upstream._current(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="перекачать, даже если уже есть")
    ap.add_argument("--versions", type=Path, help="записать versions.json и выйти")
    ap.add_argument("--manifest", type=Path, help="записать manifest.txt в папку сборки и выйти")
    ap.add_argument("--qt-runtime", type=Path, help="положить в папку сборки msvcp140*.dll из PySide6 и выйти")
    args = ap.parse_args(argv)
    if args.qt_runtime:
        print("C++-рантайм из PySide6:", ", ".join(use_qt_runtime(args.qt_runtime)) or "не найден")
        return 0
    if args.versions:
        for name, ver in write_versions(args.versions).items():
            print(f"{name}: {ver}")
        return 0
    if args.manifest:
        print(f"manifest.txt: {len(selfupdate.write_manifest(args.manifest))} файлов")
        return 0
    fetch_singbox(args.force)
    fetch_bundle(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
