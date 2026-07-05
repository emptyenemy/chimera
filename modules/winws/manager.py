"""Запуск zapret2 (winws2) с выбранной стратегией.

Стратегии — файлы strategies/*.txt (один аргумент winws2 на строку, # — коммент,
плейсхолдеры путей). Движок и бинарь берём из бандла bin/zapret-win-bundle.
Обновление zapret2 = обновление бандла + сабмодуля (см. ROADMAP).

winws2.exe требует прав администратора (манифест). Наше приложение и так
поднимается под админом ради hosts/DNS, поэтому Popen стартует без лишнего UAC.
"""

import atexit
import json
import re
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
STRATEGIES_DIR = ROOT / "strategies"
ASSETS_DIR = STRATEGIES_DIR / "assets"
HOSTLISTS_DIR = STRATEGIES_DIR / "hostlists"
WINWS_DIR = ROOT / "bin" / "zapret-win-bundle" / "zapret-winws"
WINWS_EXE = WINWS_DIR / "winws2.exe"
LOG_PATH = Path(__file__).parent / "winws.log"
STATE_PATH = Path(__file__).parent / "state.json"
# Управляется выбором списков в UI (set_lists) — перезаписывается целиком на каждое
# изменение выбора, ручные правки между изменениями переживут, но при следующем
# сохранении выбора в UI затрутся.
USER_HOSTLIST_PATH = HOSTLISTS_DIR / "list-general-user.txt"

# last_strategy — последняя успешно запущенная стратегия (восстанавливается в UI и
# для автозапуска); autostart — поднимать её при старте программы (нужен админ);
# lists — какие списки (lists/*.txt) гнать через winws — пишутся в list-general-user.txt.
DEFAULTS = {"last_strategy": None, "autostart": False, "lists": []}

_META_RE = re.compile(r"^#\s*(name|desc|source|order)\s*:\s*(.+)$", re.I)


def _abs_posix(p: Path) -> str:
    """Абсолютный путь с прямыми слешами — cygwin-winws2 принимает C:/... ."""
    return str(p.resolve()).replace("\\", "/")


def _placeholders() -> dict[str, str]:
    return {
        "{WINWS}": _abs_posix(WINWS_DIR),
        "{ASSETS}": _abs_posix(ASSETS_DIR),
        "{LISTS}": _abs_posix(HOSTLISTS_DIR),
    }


def _system_pids() -> list[int]:
    """PID всех живых winws2.exe в системе — включая запущенные ПРОШЛОЙ сессией.

    Менеджер держит только свой Popen, а winws2 от прошлого запуска приложения
    висит дальше и держит WinDivert. Чтобы честно показать состояние и уметь его
    погасить, спрашиваем систему напрямую (tasklist прав админа не требует).
    """
    name = WINWS_EXE.name
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
    except OSError:
        return []
    pids = []
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 2 and cols[0].lower() == name.lower():
            try:
                pids.append(int(cols[1]))
            except ValueError:
                pass
    return pids


# WinDivert ставит драйвер ОТДЕЛЬНОЙ службой ядра в SCM. Убить winws2 мало —
# служба остаётся RUNNING (особенно после taskkill /F). Имена менялись по версиям.
_DIVERT_SERVICES = ("windivert", "windivert14")


def _divert_status() -> str | None:
    """Статус службы WinDivert: 'RUNNING' / 'STOPPED' / None (не установлена).

    Через Get-Service, а не `sc query`: на локализованной Windows sc печатает
    «РАБОТАЕТ», а .Status у Get-Service — enum ('Running'/'Stopped'), без локали.
    """
    names = ",".join(f"'{n}'" for n in _DIVERT_SERVICES)
    ps = (
        f"$s=Get-Service -Name {names} -ErrorAction SilentlyContinue;"
        "if(-not $s){'NONE'}elseif($s|Where-Object{$_.Status -eq 'Running'}){'RUNNING'}else{'STOPPED'}"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return None
    val = out.stdout.strip()
    return None if val in ("", "NONE") else val


class WinwsManager:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._current: str | None = None
        self._error: str | None = None
        self._log = None
        # RLock: start() внутри зовёт stop(); реентрантность нужна, чтобы не словить
        # дедлок. Сериализует запуск/останов — иначе быстрые клики (переключение +
        # авто-применение фильтров) наслаивают несколько winws2 и они бьются по wf-dup-check.
        self._lock = threading.RLock()
        self.config = self._load()
        self._version_cache: str | None = None  # git-тег zapret2 в рантайме не меняется — кэшируем
        self._version_cached = False
        if not USER_HOSTLIST_PATH.exists():  # рантайм-файл, не в git — досоздать на свежем клоне
            self._regenerate_user_hostlist()
        atexit.register(self.stop)  # не оставлять winws2 висеть после закрытия приложения

    # --- конфиг (state.json) -------------------------------------------------

    def _load(self) -> dict:
        data = dict(DEFAULTS)
        if STATE_PATH.exists():
            try:
                data.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError, OSError):
                pass
        return data

    def _save(self) -> None:
        STATE_PATH.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )

    def set_autostart(self, value: bool) -> dict:
        self.config["autostart"] = bool(value)
        self._save()
        return self.state()

    def set_lists(self, names) -> dict:
        """Какие списки доменов (lists/*.txt) гнать через winws по hostlist-профилям
        стратегии. Перегенерирует list-general-user.txt и, если winws сейчас запущен,
        сразу перезапускает текущую стратегию — иначе новый список не подхватится
        (хостлист читается winws2 один раз при старте)."""
        from modules import domains
        valid = {i["name"] for i in domains.list_info()}
        self.config["lists"] = [n for n in (names or []) if n in valid]
        self._save()
        self._regenerate_user_hostlist()
        sid = self._current or self.config.get("last_strategy")
        if self.running and sid:
            self.start(sid)
        return self.state()

    def _regenerate_user_hostlist(self) -> None:
        from modules import domains
        seen, out = set(), []
        for d in domains.load_lists(self.config.get("lists") or []):
            d = d.strip().lower().lstrip(".")
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        text = ("\n".join(out) + "\n") if out else ""
        USER_HOSTLIST_PATH.write_text(text, encoding="utf-8")

    def autostart(self) -> dict | None:
        """Поднять последнюю стратегию при старте программы, если включён автозапуск.

        Вызывается из Api.__init__. Молча ничего не делает, если автозапуск выключен,
        стратегия не сохранена или её файл удалён — старт без админа бросит наверх (как
        proxy/tg, ошибка уедет в UI через winws_state)."""
        sid = self.config.get("last_strategy")
        if not self.config.get("autostart") or not sid:
            return None
        if not (STRATEGIES_DIR / f"{sid}.txt").exists():
            return None
        return self.start(sid)

    # --- стратегии -----------------------------------------------------------

    def _strategy_path(self, strategy_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", strategy_id or ""):
            raise ValueError("Недопустимый id стратегии")
        path = STRATEGIES_DIR / f"{strategy_id}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Стратегия {strategy_id!r} не найдена")
        return path

    def _parse_meta(self, path: Path) -> dict:
        meta = {"id": path.stem, "name": path.stem, "desc": "", "source": "", "order": "999"}
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _META_RE.match(line.strip())
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
            elif line.strip() and not line.startswith("#"):
                break  # метаданные только в шапке
        return meta

    def strategies(self) -> list[dict]:
        """Список стратегий, отсортированный по полю `order` шапки (затем по id)."""
        if not STRATEGIES_DIR.exists():
            return []
        metas = [self._parse_meta(p) for p in STRATEGIES_DIR.glob("*.txt")]

        def key(m):
            try:
                o = int(m.get("order", 999))
            except (TypeError, ValueError):
                o = 999
            return (o, m["id"])

        return sorted(metas, key=key)

    def build_args(self, strategy_id: str) -> list[str]:
        """Аргументы winws2 из файла стратегии (без самого exe)."""
        path = self._strategy_path(strategy_id)
        subs = _placeholders()
        lines: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for ph, val in subs.items():
                line = line.replace(ph, val)
            lines.append(line)
        return self._apply_game_filter(lines)

    @staticmethod
    def _apply_game_filter(lines: list[str]) -> list[str]:
        """Game-фильтр: подставляет игровые порты в --wf-*-out и оставляет/убирает
        игровые профили (--filter-tcp/udp={GAME_*}) в зависимости от режима.

        Сами игровые профили теперь в .txt каждой стратегии (per-strategy десинк,
        1:1 с Flowseal) — здесь только их включение/выключение и порты захвата.
        {GAME_*_WF} -> ',1024-65535' в --wf-*-out (или пусто), блок с {GAME_*} в
        --filter-* выкидывается целиком, если соответствующий режим выключен."""
        from modules.winws import filters
        gp = filters.game_ports()  # {'tcp':ports|None,'udp':ports|None} или None
        tcp = gp["tcp"] if gp else None
        udp = gp["udp"] if gp else None

        out = []
        for a in lines:
            a = a.replace("{GAME_TCP_WF}", ("," + tcp) if tcp else "")
            a = a.replace("{GAME_UDP_WF}", ("," + udp) if udp else "")
            out.append(a)

        blocks, cur = [], []
        for a in out:
            if a == "--new":
                blocks.append(cur)
                cur = []
            else:
                cur.append(a)
        blocks.append(cur)

        kept = []
        for b in blocks:
            txt = "\n".join(b)
            if "{GAME_TCP}" in txt:
                if not tcp:
                    continue
                b = [x.replace("{GAME_TCP}", tcp) for x in b]
            if "{GAME_UDP}" in txt:
                if not udp:
                    continue
                b = [x.replace("{GAME_UDP}", udp) for x in b]
            kept.append(b)

        args = []
        for i, b in enumerate(kept):
            if i:
                args.append("--new")
            args += b
        return args

    # --- жизненный цикл ------------------------------------------------------

    @property
    def _ours_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def running(self) -> bool:
        """Жив ли winws2 ВООБЩЕ — наш или оставшийся от прошлой сессии."""
        return self._ours_alive or bool(_system_pids())

    def start(self, strategy_id: str) -> dict:
        with self._lock:
            if self.running:
                # перезапуск/переключение: глушим старый winws2 (и ЖДЁМ его смерти в
                # _kill_leftovers), но службу WinDivert НЕ удаляем — новый инстанс её
                # переиспользует. Иначе delete+пересоздание драйвера флакает.
                self.stop(clean_divert=False)
            if not WINWS_EXE.exists():
                raise FileNotFoundError(
                    "winws2.exe не найден в бандле. Проверь bin/zapret-win-bundle/zapret-winws."
                )
            args = self.build_args(strategy_id)
            self._error = None
            # вывод winws2 — в файл, не в PIPE: процесс долгоживущий и болтливый,
            # неосушаемый PIPE-буфер забьётся и повесит winws2.
            self._log = open(LOG_PATH, "w", encoding="utf-8")
            try:
                self._proc = subprocess.Popen(
                    [str(WINWS_EXE), *args],
                    cwd=str(WINWS_DIR),  # рядом WinDivert.dll/драйвер
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError as e:
                self._close_log()
                self._proc = None
                raise RuntimeError(f"Не удалось запустить winws2: {e}") from e
            self._current = strategy_id
            # ловим мгновенную смерть (битые аргументы, нет прав, занят драйвер)
            time.sleep(1.0)
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self._proc = None
                self._current = None
                self._close_log()
                self._error = self._read_error(code)
                raise RuntimeError(self._error)
            # стратегия поднялась — запоминаем для восстановления выбора и автозапуска
            if self.config.get("last_strategy") != strategy_id:
                self.config["last_strategy"] = strategy_id
                self._save()
            return self.state()

    def _read_error(self, code: int) -> str:
        """Сообщение об ошибке из лога winws2.

        winws2 при битом аргументе печатает строку-диагностику `winws2: ...`,
        а СЛЕДОМ вываливает весь usage. Тащить хвост лога в ошибку нельзя — туда
        попадёт простыня help'а, а не причина. Берём именно строки `winws2: ...`.
        """
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        diag = [ln.strip() for ln in lines if ln.strip().lower().startswith("winws2:")]
        if not diag:  # неизвестный формат — отдаём последние непустые строки
            diag = [ln.strip() for ln in lines if ln.strip()][-4:]
        detail = " | ".join(diag) if diag else "нет вывода"
        return f"winws2 завершился (код {code}). {detail}"

    def log_read(self, offset: int = 0) -> dict:
        """Инкрементальное чтение лога winws2 (живой стрим в UI)."""
        from modules import logutil
        return logutil.read_from(LOG_PATH, offset)

    def _close_log(self):
        if self._log:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    def stop(self, clean_divert: bool = True) -> dict:
        with self._lock:
            # 1) свой процесс — мягко, потом жёстко
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            self._current = None
            self._close_log()
            # 2) добиваем все оставшиеся winws2 (в т.ч. от прошлой сессии) и ждём смерти
            self._kill_leftovers()
            # 3) выгружаем и удаляем службу WinDivert — иначе драйвер ядра остаётся
            #    висеть RUNNING. Пропускаем при перезапуске (clean_divert=False).
            if clean_divert:
                self._stop_divert()
            return self.state()

    @staticmethod
    def _kill_leftovers() -> None:
        if not _system_pids():
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", WINWS_EXE.name],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            pass
        # ЖДЁМ фактической смерти: иначе следующий winws2 стартует, пока старый ещё
        # держит wf-фильтр, ловит wf-dup-check и падает (код 1), хотя «capture is
        # started» уже залогировал. Без этого переключение/рестарт флакают.
        for _ in range(20):  # до ~3 c
            if not _system_pids():
                return
            time.sleep(0.15)

    @staticmethod
    def _stop_divert() -> None:
        """Остановить и удалить службу(ы) WinDivert (как Remove Services у Flowseal).

        winws2 уже убит, так что хендлов на драйвере нет — `sc stop` его выгрузит.
        `sc delete` снимает регистрацию; при следующем старте WinDivert создаст
        службу заново сам. Требует прав админа — приложение и так под админом.
        """
        if _divert_status() is None:
            return
        for name in _DIVERT_SERVICES:
            for action in ("stop", "delete"):
                try:
                    subprocess.run(
                        ["sc", action, name],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except OSError:
                    pass

    # --- состояние -----------------------------------------------------------

    def version(self) -> str | None:
        """Версия zapret2 из сабмодуля (git-тег). Для отображения в UI.

        Кэшируем: тег в рантайме не меняется, а `git describe` на каждый опрос
        дашборда (раз в 3 c) — лишний процесс и заметный вклад в лаги.
        """
        if self._version_cached:
            return self._version_cache
        try:
            out = subprocess.run(
                ["git", "-C", str(ROOT / "upstream" / "zapret2"), "describe", "--tags"],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._version_cache = out.stdout.strip() or None
        except Exception:
            self._version_cache = None
        self._version_cached = True
        return self._version_cache

    def state(self) -> dict:
        from modules import domains
        ours = self._ours_alive
        running = ours or bool(_system_pids())
        return {
            "running": running,
            # external = winws2 жив, но это не наш Popen (остался от прошлой сессии):
            # стратегию мы не знаем, но показать и дать остановить — обязаны.
            "external": running and not ours,
            "current": self._current if ours else None,
            # last_strategy переживает перезапуск программы (в отличие от current):
            # UI подсвечивает её, даже когда winws2 не запущен.
            "last_strategy": self.config.get("last_strategy"),
            "autostart": bool(self.config.get("autostart")),
            # списки доменов, которые гонит через себя winws (list-general-user.txt)
            "lists": self.config.get("lists") or [],
            "all_lists": [i["name"] for i in domains.list_info()],
            "list_domains": len(domains.load_lists(self.config.get("lists") or [])),
            # статус драйвера WinDivert (служба ядра живёт отдельно от winws2):
            "windivert": _divert_status(),  # RUNNING / STOPPED / None
            "version": self.version(),
            "error": self._error,
        }
