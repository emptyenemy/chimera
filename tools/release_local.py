"""Выпуск без GitHub Actions: три сборки, проверки, архивы, SHA256 и релиз на GitHub.

    build\\build-clean313\\Scripts\\python.exe tools/release_local.py 1.0.3             собрать и проверить
    build\\build-clean313\\Scripts\\python.exe tools/release_local.py 1.0.3 --publish   и выложить

Нужны Python 3.13 и Nuitka 4.2.2 в чистом venv (build.bat проверит версии), Node 22+ и gh с входом.
Версия пишется в modules/version.py только на время сборки и возвращается назад.

Сначала — всё, что гоняет CI: ruff, pytest, lint, typecheck и тесты фронта, живой интерфейс
в headless Edge (tools/smoke_*.py). Красный тест останавливает выпуск до сборки.
Потом проверки release.yml, кроме системных (--full меняет систему — только для
одноразовой машины): дымовой тест сборки, проверка распакованного архива и настоящее
обновление прошлого релиза до нового Qt-архива. Окно программы на экране проверки не
открывают; запуск двойным кликом — с --window.

--publish ставит тег на HEAD (он уже должен быть в origin/main), пушит его и создаёт
релиз с тремя архивами. Пуш тега Actions не запускает.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import release_notes  # noqa: E402
from modules.version import parse  # noqa: E402

REPO = "emptyenemy/chimera"
FLAVORS = {"qt": ("Chimera", ""), "webview": ("Chimera-webview", "-webview"), "lite": ("Chimera-lite", "-lite")}


FRONTEND = ROOT / "frontend"
# живой интерфейс в headless Edge, без окна на экране; smoke_native_appearance открывает окно — не здесь
UI_SMOKES = ("smoke_appearance.py", "smoke_layout.py", "smoke_autosave.py", "smoke_filters.py",
             "smoke_checks.py", "smoke_trials.py", "smoke_verified_config.py", "smoke_autotune.py")


def run(*argv, cwd=ROOT, **kwargs):
    print("$", " ".join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv], cwd=cwd, check=True, **kwargs)


def out(*argv):
    return subprocess.run([str(a) for a in argv], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def previous_release(version):
    """Последний опубликованный релиз до этого — с него проверяется обновление."""
    tags = out("gh", "release", "list", "--repo", REPO, "--exclude-drafts", "--limit", "30",
               "--json", "tagName", "--jq", ".[].tagName").split()
    older = [t.removeprefix("v") for t in tags if t.removeprefix("v") != version and parse(t.removeprefix("v"))]
    return max(older, key=parse) if older else None


def check_tree(publish):
    if out("git", "status", "--porcelain", "--untracked-files=no"):
        sys.exit("[!] В рабочей копии есть незакоммиченные правки: сборка должна совпадать с коммитом.")
    if publish:
        run("git", "fetch", "origin", "main", "--tags", "--force")
        if subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], cwd=ROOT).returncode:
            sys.exit("[!] HEAD ещё не в origin/main: сначала git push.")


def test_all(env):
    """Всё, что гоняет CI, кроме окна на экране: красный тест останавливает выпуск до сборки."""
    run(sys.executable, "-m", "ruff", "check", ".", env=env)
    run(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", env=env)
    for script in ("ci", "run lint", "run typecheck", "test", "run build"):
        run("cmd", "/c", "npm", *script.split(), cwd=FRONTEND, env=env)
    for smoke in UI_SMOKES:
        run(sys.executable, ROOT / "tools" / smoke, env=env)


def build(flavor, version, env):
    folder, _ = FLAVORS[flavor]
    run("cmd", "/c", ROOT / "build.bat", flavor, env=env)
    exe = ROOT / "build" / folder / "Chimera.exe"
    reported = out(exe, "--version")
    if version not in reported:
        sys.exit(f"[!] {folder}: exe сообщает «{reported}», ожидалась {version}.")
    run(sys.executable, "tools/smoke_build.py", ROOT / "build" / folder, "--flavor", flavor)


def pack(flavor, version, dist, window):
    folder, suffix = FLAVORS[flavor]
    base = dist / f"Chimera-{version}-win64{suffix}"
    archive = Path(shutil.make_archive(str(base), "zip", root_dir=ROOT / "build", base_dir=folder))
    verify = [sys.executable, "tools/verify_archive.py", archive, "--flavor", flavor, "--version", version]
    run(*verify, *([] if window else ["--no-window"]))
    return archive


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish(version, archives, notes):
    tag = f"v{version}"
    head = out("git", "rev-parse", "HEAD")
    local = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if local and local != head:
        sys.exit(f"[!] Тег {tag} уже стоит на {local[:7]}, а собран {head[:7]}: сначала убрать старый тег.")
    if not local:
        run("git", "tag", "-a", tag, "-m", f"Chimera {version}")
    run("git", "push", "origin", f"refs/tags/{tag}")
    flags = ["--title", f"Chimera {tag}", "--notes-file", notes, "--verify-tag"]
    if "-" in version:
        flags.append("--prerelease")
    run("gh", "release", "create", tag, *archives, "--repo", REPO, *flags)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version")
    parser.add_argument("--flavors", default="qt,webview,lite")
    parser.add_argument("--publish", action="store_true", help="Поставить тег и создать релиз на GitHub")
    parser.add_argument("--skip-build", action="store_true", help="Взять готовые папки build/ (той же версии)")
    parser.add_argument("--skip-tests", action="store_true", help="Не гонять тесты исходников (уже прошли на этом коммите)")
    parser.add_argument("--window", action="store_true", help="Проверить и запуск двойным кликом (откроет окно)")
    args = parser.parse_args()

    version = args.version.removeprefix("v")
    if parse(version) is None:
        sys.exit(f"[!] {version!r} — не версия.")
    flavors = [f.strip() for f in args.flavors.split(",") if f.strip()]
    if unknown := set(flavors) - set(FLAVORS):
        sys.exit(f"[!] Неизвестные варианты: {', '.join(sorted(unknown))}.")
    if args.publish and set(flavors) != set(FLAVORS):
        sys.exit("[!] Релиз выходит только с тремя архивами.")
    check_tree(args.publish)
    release_notes.render(version)  # нет заметок RU/EN — падаем до двадцатиминутной сборки

    dist = ROOT / "build" / f"release-{version}"
    shutil.rmtree(dist, ignore_errors=True)
    dist.mkdir(parents=True)
    # build.bat зовёт просто python: тот же интерпретатор, что запустил этот скрипт
    scripts = Path(sys.executable).parent
    env = {**os.environ, "PATH": os.pathsep.join([str(scripts), os.environ.get("PATH", "")]),
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if not args.skip_tests:
        test_all(env)
    if not args.skip_build:
        run(sys.executable, "tools/fetch_bins.py", env=env)  # уже скачанное не трогает
    try:
        run(sys.executable, "tools/set_version.py", version)
        archives = []
        for flavor in flavors:
            if not args.skip_build:
                build(flavor, version, env)
            archives.append(pack(flavor, version, dist, args.window))
    finally:
        run("git", "checkout", "--", "modules/version.py")

    previous = previous_release(version)
    if "qt" in flavors and previous:
        run(sys.executable, "tools/verify_upgrade.py", dist / f"Chimera-{version}-win64.zip",
            "--version", version, "--from-version", previous)
    checksums = "".join(f"{sha256(a)}  {a.name}\n" for a in archives)
    (dist / "checksums.txt").write_text(checksums, encoding="utf-8", newline="\n")
    notes = dist / "release-notes.txt"
    notes.write_text(release_notes.render(version, checksums), encoding="utf-8", newline="\n")
    print(json.dumps({"version": version, "archives": [a.name for a in archives], "dist": str(dist),
                      "upgrade_from": previous}, ensure_ascii=False), flush=True)
    if args.publish:
        publish(version, archives, notes)


if __name__ == "__main__":
    main()
