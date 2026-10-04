"""Стратегии и списки по воздуху: обновление данных без новой версии программы.

Данные — стратегии winws2, их хостлисты и fake-блобы, списки сайтов. Выпускаются
отдельными релизами на GitHub с тегом data-ГГГГ.ММ.ДД[.N] (tools/release_data.py):
архив chimera-data-<версия>.zip и манифест chimera-data-<версия>.json с SHA256 каждого
файла. Самообновление такие релизы пропускает: тег не версия, архив не программы.

Свои правки пользователя не трогаются. Файл обновляется, только если он «нетронутый»:
его хеш совпадает с одной из версий, которые ставила сама Chimera — пришедшей в сборке
(data-manifest.json рядом с exe) или прошлым обновлением данных (data/data-update.json).
Изменённый пользователем файл остаётся как есть, это видно в предпросмотре. Файлы,
которых нет в новом выпуске, не удаляются: на них могут ссылаться выбранная стратегия
и подключённые к модулям списки.
"""

import fnmatch
import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from modules import paths
from modules.errors import ChimeraError
from modules.fileutil import atomic_write_text
from modules.version import VERSION, is_newer, parse

RELEASES_API = "https://api.github.com/repos/emptyenemy/chimera/releases?per_page=30"
TAG_PREFIX = "data-"
VERSION_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}(?:\.\d{1,3})?")
SHIPPED_NAME = "data-manifest.json"
SHIPPED = paths.APP_DIR / SHIPPED_NAME
STATE = paths.data_path("data-update.json")
MAX_BYTES = 32 << 20   # данные — сотни килобайт; больше — не наш архив
_HTTP_TIMEOUT = 15

# что входит в данные (пути от корня программы, через /)
PATTERNS = ("strategies/*.txt", "strategies/hostlists/*.txt", "strategies/assets/*.bin", "lists/*.txt",
            "strategies/provider-map.json")
# файлы пользователя рядом с данными: их не публикуем и не трогаем
USER_FILES = ("strategies/hostlists/ipset-all.txt", "strategies/assets/ACTIVE_DISCORD_UDP.bin",
              "strategies/assets/ACTIVE_GAME_UDP.bin")


def is_data_path(rel: str) -> bool:
    if not isinstance(rel, str) or "\\" in rel or rel.startswith("/") or ".." in rel.split("/"):
        return False
    if rel in USER_FILES or rel.endswith("-user.txt"):
        return False
    return any(fnmatch.fnmatchcase(rel, p) and rel.count("/") == p.count("/") for p in PATTERNS)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(root: Path) -> dict:
    """{путь: sha256} всех файлов данных под root — для сборки и выпуска данных."""
    files = {}
    for pattern in PATTERNS:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and is_data_path(rel):
                files[rel] = sha256(path.read_bytes())
    return files


def version_key(version: str):
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        return None
    return tuple(int(p) for p in version.split("."))


def write_shipped(root: Path, version: str) -> dict:
    """Манифест данных, с которыми выходит сборка (зовётся из tools/finish_build.py)."""
    manifest = {"schema": 1, "version": version, "files": collect(root)}
    (root / SHIPPED_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_manifest(data) -> bool:
    files = data.get("files") if isinstance(data, dict) else None
    return (isinstance(data, dict) and data.get("schema") == 1 and version_key(data.get("version")) is not None
            and isinstance(files, dict) and all(is_data_path(k) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                                                for k, v in files.items()))


class DataUpdater:
    def __init__(self, root: Path = None, shipped: Path = None, state: Path = None, *, app_version: str = VERSION,
                 frozen: bool = None, fetch=None, opener=urllib.request.urlopen):
        self.root = root or paths.APP_DIR
        self.shipped_path = shipped or self.root / SHIPPED_NAME
        self.state_path = state or STATE
        self.app_version = app_version
        self.frozen = paths.IS_FROZEN if frozen is None else frozen
        self.fetch = fetch or self._fetch_json
        self.opener = opener

    # --- что стоит сейчас ---------------------------------------------------------------

    def _shipped(self) -> dict:
        data = _read_json(self.shipped_path)
        return data if _valid_manifest(data) else {}

    def _state(self) -> dict:
        data = _read_json(self.state_path)
        if version_key(data.get("version")) is None or not isinstance(data.get("pristine"), dict):
            return {}
        return data

    def installed(self) -> str | None:
        """Версия данных: последнее обновление, если оно новее того, что пришло в сборке."""
        shipped, state = self._shipped().get("version"), self._state().get("version")
        versions = [v for v in (shipped, state) if version_key(v)]
        return max(versions, key=version_key) if versions else None

    def _pristine(self) -> dict:
        known = {}
        for rel, digest in self._shipped().get("files", {}).items():
            known.setdefault(rel, set()).add(digest)
        for rel, digests in self._state().get("pristine", {}).items():
            if isinstance(digests, list):
                known.setdefault(rel, set()).update(d for d in digests if isinstance(d, str))
        return known

    def _local(self, rel: str) -> str | None:
        path = self.root / rel
        try:
            return sha256(path.read_bytes()) if path.is_file() else None
        except OSError:
            return None

    def preview(self, manifest: dict) -> dict:
        """Что изменит выпуск: добавит, обновит, оставит (изменено пользователем)."""
        pristine = self._pristine()
        plan = {"add": [], "update": [], "keep": [], "same": 0}
        for rel, digest in sorted(manifest["files"].items()):
            local = self._local(rel)
            if local is None:
                plan["add"].append(rel)
            elif local == digest:
                plan["same"] += 1
            elif local in pristine.get(rel, ()):
                plan["update"].append(rel)
            else:
                plan["keep"].append(rel)
        return plan

    # --- проверка -------------------------------------------------------------------------

    @staticmethod
    def _fetch_json(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "chimera", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read(MAX_BYTES).decode("utf-8"))

    @staticmethod
    def _asset(release: dict, suffix: str) -> dict | None:
        for a in release.get("assets") or []:
            name = a.get("name", "")
            if name.startswith("chimera-data-") and name.endswith(suffix):
                digest = a.get("digest") or ""
                return {"name": name, "url": a.get("browser_download_url"), "size": a.get("size") or 0,
                        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None}
        return None

    def _latest_release(self, releases) -> dict | None:
        best = None
        for r in releases or []:
            tag = r.get("tag_name", "")
            key = version_key(tag[len(TAG_PREFIX):]) if tag.startswith(TAG_PREFIX) else None
            if r.get("draft") or key is None or not self._asset(r, ".zip") or not self._asset(r, ".json"):
                continue
            if best is None or key > best[0]:
                best = (key, r)
        return best[1] if best else None

    def _download(self, asset: dict) -> bytes:
        if not asset.get("url") or not asset.get("sha256"):
            raise ChimeraError("err.data.unverified")
        req = urllib.request.Request(asset["url"], headers={"User-Agent": "chimera"})
        with self.opener(req, timeout=_HTTP_TIMEOUT * 4) as resp:
            body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES or sha256(body) != asset["sha256"]:
            raise ChimeraError("err.data.checksum")
        return body

    def _resolve(self):
        """Последний выпуск данных и его проверенный манифест; (None, None), если выпусков нет."""
        release = self._latest_release(self.fetch(RELEASES_API))
        if release is None:
            return None, None
        manifest = json.loads(self._download(self._asset(release, ".json")).decode("utf-8"))
        if not _valid_manifest(manifest):
            raise ChimeraError("err.data.invalid")
        return release, manifest

    def check(self) -> dict:
        """Есть ли выпуск данных новее установленного и что он изменит. Сеть — поле error."""
        info, _release, _manifest = self._check()
        return info

    def _check(self, strict=False):
        """strict — для установки: ошибки бросаются, а не кладутся в поле error."""
        base = {"current": self.installed(), "latest": None, "update": False, "installable": False,
                "plan": None, "min_app": None, "error": None}
        try:
            if not self.frozen:
                raise ChimeraError("err.data.source_run")
            try:
                release, manifest = self._resolve()
            except (urllib.error.URLError, OSError, ValueError):
                raise ChimeraError("err.data.network") from None
        except ChimeraError as e:
            if strict:
                raise
            return {**base, "error": e.code}, None, None
        if release is None:
            return base, None, None
        latest, current = manifest["version"], base["current"]
        newer = current is None or version_key(latest) > version_key(current)
        min_app = manifest.get("min_app")
        app_ok = not (isinstance(min_app, str) and parse(min_app) and parse(self.app_version)
                      and is_newer(min_app, self.app_version))
        info = {**base, "latest": latest, "update": newer, "installable": newer and app_ok,
                "plan": self.preview(manifest), "min_app": min_app, "release": release.get("tag_name")}
        return info, release, manifest

    # --- установка ------------------------------------------------------------------------

    def _unpack(self, body: bytes, manifest: dict) -> dict:
        """Файлы архива строго по манифесту: ни лишних, ни чужих путей, хеши совпали."""
        with tempfile.TemporaryDirectory(prefix="chimera-data-") as tmp:
            archive = Path(tmp) / "data.zip"
            archive.write_bytes(body)
            with zipfile.ZipFile(archive) as z:
                names = [i.filename for i in z.infolist() if not i.is_dir()]
                if set(names) != set(manifest["files"]) or len(names) != len(set(names)):
                    raise ChimeraError("err.data.invalid")
                files = {}
                for name in names:
                    data = z.read(name)
                    if sha256(data) != manifest["files"][name]:
                        raise ChimeraError("err.data.checksum")
                    files[name] = data
        return files

    def install(self, before=None) -> dict:
        """Скачать и применить последний выпуск. before(changed) — снимок до записи (бэкап)."""
        info, release, manifest = self._check(strict=True)
        if not info["installable"]:
            if info["update"]:
                raise ChimeraError("err.data.app_too_old")
            raise ChimeraError("err.data.nothing")
        files = self._unpack(self._download(self._asset(release, ".zip")), manifest)
        plan = self.preview(manifest)
        changed = plan["add"] + plan["update"]
        if before is not None:
            before(changed)
        for rel in changed:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".data-new")
            temp.write_bytes(files[rel])
            temp.replace(target)
        state = self._state()
        pristine = {rel: list(digests) for rel, digests in state.get("pristine", {}).items() if isinstance(digests, list)}
        # «нетронутые» — все версии, которые публиковала Chimera: пользователь мог и сам
        # прийти к одной из них, тогда файл снова обновляется как обычный
        for rel, digest in manifest["files"].items():
            known = pristine.setdefault(rel, [])
            if digest not in known:
                known.append(digest)
        atomic_write_text(self.state_path, json.dumps({"version": manifest["version"], "pristine": pristine},
                                                      ensure_ascii=False, indent=1))
        return {"version": manifest["version"], "added": plan["add"], "updated": plan["update"], "kept": plan["keep"]}

