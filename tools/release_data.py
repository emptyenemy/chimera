"""Выпуск стратегий и списков по воздуху: архив данных и манифест — релиз data-ГГГГ.ММ.ДД.N на GitHub.

    build\\build-clean313\\Scripts\\python.exe tools/release_data.py             собрать и сравнить с прошлым выпуском
    build\\build-clean313\\Scripts\\python.exe tools/release_data.py --publish   и выложить

Данные берутся из рабочей копии (стратегии, хостлисты, fake-блобы и списки — то же,
что modules/dataupdate.is_data_path); для --publish она должна быть чистой и уже в
origin/main. min_app — последняя опубликованная версия программы: данные не придут
к программе старше той, с которой их проверяли. Релиз не помечается последним
(--latest=false), самообновление программы его не видит; хранятся три последних
выпуска данных, чтобы не вытеснять из списка релизов сами версии программы.
"""

import argparse
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules import dataupdate  # noqa: E402
from modules.version import parse  # noqa: E402

REPO = "emptyenemy/chimera"
KEEP = 3


def out(*argv) -> str:
    return subprocess.run([str(a) for a in argv], cwd=ROOT, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def run(*argv):
    print("$", " ".join(str(a) for a in argv), flush=True)
    subprocess.run([str(a) for a in argv], cwd=ROOT, check=True)


def releases() -> list[dict]:
    return json.loads(out("gh", "release", "list", "--repo", REPO, "--limit", "100", "--json", "tagName,isPrerelease"))


def published_data(items) -> list[str]:
    versions = [r["tagName"][5:] for r in items if r["tagName"].startswith(dataupdate.TAG_PREFIX)]
    return sorted((v for v in versions if dataupdate.version_key(v)), key=dataupdate.version_key, reverse=True)


def latest_app(items) -> str | None:
    versions = [r["tagName"].removeprefix("v") for r in items
                if r["tagName"].startswith("v") and not r.get("isPrerelease") and parse(r["tagName"].removeprefix("v"))]
    return max(versions, key=parse) if versions else None


def next_version(existing, today=None) -> str:
    """ГГГГ.ММ.ДД.N: номер растёт внутри дня. Сборка того же дня — ГГГГ.ММ.ДД, она всегда старше."""
    base = today or time.strftime("%Y.%m.%d")
    taken = [int(v.split(".")[3]) for v in existing if v.startswith(base + ".") and v.count(".") == 3]
    return f"{base}.{max(taken, default=0) + 1}"


def diff(old: dict, new: dict) -> dict:
    return {"added": sorted(set(new) - set(old)), "changed": sorted(k for k in new if k in old and new[k] != old[k]),
            "removed": sorted(set(old) - set(new))}


def build(version: str, min_app: str | None, dist: Path) -> tuple[dict, Path, Path]:
    files = dataupdate.collect(ROOT)
    manifest = {"schema": 1, "version": version, "files": files}
    if min_app:
        manifest["min_app"] = min_app
    dist.mkdir(parents=True, exist_ok=True)
    archive = dist / f"chimera-data-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            # фиксированная дата: один и тот же набор файлов даёт одинаковый архив
            info = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (ROOT / rel).read_bytes())
    manifest_path = dist / f"chimera-data-{version}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest, archive, manifest_path


def previous_manifest(version: str, dist: Path) -> dict:
    target = dist / "previous.json"
    out("gh", "release", "download", f"data-{version}", "--repo", REPO, "-p", f"chimera-data-{version}.json",
        "-O", target, "--clobber")
    return json.loads(target.read_text(encoding="utf-8"))


def notes(changes: dict) -> str:
    lines = ["Стратегии и списки для Chimera без новой версии программы. Ставятся из программы: "
             "Настройки → Обновление → Стратегии и списки, или `chimera data update`.", ""]
    for key, title in (("added", "Добавлено"), ("changed", "Обновлено"), ("removed", "Убрано из выпуска")):
        if changes[key]:
            lines.append(f"**{title}:** " + ", ".join(f"`{p}`" for p in changes[key]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--min-app", help="Самая старая версия Chimera, которой подходят эти данные")
    args = parser.parse_args()
    if args.publish:
        if out("git", "status", "--porcelain", "--untracked-files=no"):
            sys.exit("[!] В рабочей копии есть незакоммиченные правки: выпуск должен совпадать с коммитом.")
        run("git", "fetch", "origin", "main")
        if subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], cwd=ROOT).returncode:
            sys.exit("[!] HEAD ещё не в origin/main: сначала git push.")
    items = releases()
    existing = published_data(items)
    version = next_version(existing)
    min_app = args.min_app or latest_app(items)
    dist = ROOT / "build" / f"data-{version}"
    manifest, archive, manifest_path = build(version, min_app, dist)
    previous = previous_manifest(existing[0], dist)["files"] if existing else {}
    changes = diff(previous, manifest["files"])
    print(json.dumps({"version": version, "min_app": min_app, "files": len(manifest["files"]),
                      **{k: len(v) for k, v in changes.items()}}, ensure_ascii=False), flush=True)
    if existing and not any(changes.values()):
        print("Нечего выпускать: данные совпадают с выпуском", existing[0])
        return
    if not args.publish:
        return
    head = out("git", "rev-parse", "HEAD")
    run("gh", "release", "create", f"data-{version}", archive, manifest_path, "--repo", REPO, "--target", head,
        "--title", f"Стратегии и списки {version}", "--notes", notes(changes), "--latest=false")
    for old in existing[KEEP - 1:]:
        run("gh", "release", "delete", f"data-{old}", "--repo", REPO, "--yes", "--cleanup-tag")


if __name__ == "__main__":
    main()
