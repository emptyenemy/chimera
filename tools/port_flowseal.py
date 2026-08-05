#!/usr/bin/env python3
"""Портирование стратегий Flowseal (winws1/.bat) -> формат CHIMERA (winws2/.txt).

Зачем генератор, а не ручная правка: каждая стратегия Flowseal — это 7-9 профилей
с десятками числовых параметров (repeats, split-pos, seqovl, cutoff). Переписывать
их руками 1:1 для 20 файлов — гарантированные опечатки. Транслятор читает .bat и
МЕХАНИЧЕСКИ переводит winws1 --dpi-desync-* в winws2 --lua-desync. Числа берутся
прямо из источника => перевод дословный. Файл оставлен для аудита/регенерации.

Соответствия (выверены по upstream/zapret2/lua/zapret-antidpi.lua,
preset2_example.cmd и blockcheck2.d/{standard,custom}):
  --dpi-desync=fake                 -> --lua-desync=fake:blob=<имя>
  --dpi-desync=multisplit/...split  -> --lua-desync=multisplit:pos=P:seqovl=S:seqovl_pattern=<blob>
  --dpi-desync=multidisorder        -> --lua-desync=multidisorder:pos=...
  --dpi-desync=fakedsplit           -> --lua-desync=fakedsplit:pos=P:pattern=<blob> (+fooling+repeats)
  --dpi-desync=hostfakesplit        -> --lua-desync=hostfakesplit:host=H (+fooling+repeats)
  --dpi-desync=syndata              -> --lua-desync=syndata
  fooling=ts                        -> tcp_ts=-1000
  fooling=badseq (+increment=N)     -> tcp_seq=N
  fooling=md5sig                    -> tcp_md5
  --ip-id=zero                      -> ip_id=zero
  --dpi-desync-cutoff=nN            -> --out-range=-nN
  --dpi-desync-any-protocol=1       -> --payload=all
  --dpi-desync-fake-tls-mod=...     -> tls_mod=... (на авто-фейке)
ПРАВИЛО (preset2): в связке fake,<split> fooling+repeats идут ТОЛЬКО на fake;
multisplit/multidisorder получают лишь pos/seqovl (реальные сегменты не портим).
fakedsplit/fakeddisorder/hostfakesplit получают fooling+repeats (у них свои фейки).

Источник по умолчанию — пиннутый сабмодуль upstream/zapret-discord-youtube
(Flowseal). Путь можно переопределить аргументом.

Запуск:  python tools/port_flowseal.py [path/to/zapret-discord-youtube]
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "strategies"
DEFAULT_SRC = ROOT / "upstream" / "zapret-discord-youtube"

# Хостлисты Flowseal берём как есть — они не генерируются, но обновляются вместе
# со стратегиями (в 1.10.0 переехал live-video.net, добавилась пачка исключений).
# Синхроним прямо тут: иначе после обновления сабмодуля стратегии свежие, а списки
# отстают, и десинк уходит не на те домены.
# Не трогаем: *-user.txt (наши, пользовательские) и ipset-all.txt — у Flowseal в
# репозитории заглушка, реальный список качается отдельно (modules/winws/filters.py).
SYNC_LISTS = ("list-general.txt", "list-google.txt", "list-exclude.txt", "ipset-exclude.txt")

# имя .bat -> (id, отображаемое имя, порядок в UI, описание)
STRATS = {
    "general.bat": ("general", "GENERAL", 20,
                    "База Flowseal: multisplit с seqovl поверх fake-блобов (google/4pda)."),
    "general (ALT).bat": ("alt", "ALT", 30,
                          "fake + fakedsplit (паттерн 0x00, fooling=ts)."),
    "general (ALT2).bat": ("alt2", "ALT2", 31,
                           "multisplit pos=2 seqovl=652 (google-паттерн)."),
    "general (ALT3).bat": ("alt3", "ALT3", 32,
                           "fake (tls-mod rnd/dupsid/sni) + hostfakesplit (поддельный SNI)."),
    "general (ALT4).bat": ("alt4", "ALT4", 33,
                           "fake + multisplit, fooling=badseq (+1000)."),
    "general (ALT5).bat": ("alt5", "ALT5", 34,
                           "syndata + multidisorder. NOT RECOMMENDED (без TLS-профилей)."),
    "general (ALT6).bat": ("alt6", "ALT6", 35,
                           "multisplit pos=1 seqovl=681 (google-паттерн везде)."),
    "general (ALT7).bat": ("alt7", "ALT7", 36,
                           "multisplit pos=2,sniext+1 seqovl=679; fallback — syndata."),
    "general (ALT8).bat": ("alt8", "ALT8", 37,
                           "чистый fake, fooling=badseq (+2)."),
    "general (ALT9).bat": ("alt9", "ALT9", 38,
                           "hostfakesplit (host=google/ozon), fooling=ts(/md5sig)."),
    "general (ALT10).bat": ("alt10", "ALT10", 39,
                            "fake с 4pda-блобом в общем TLS-профиле, fooling=ts."),
    "general (ALT11).bat": ("alt11", "ALT11", 40,
                            "fake + multisplit seqovl, repeats=8/11, fooling=ts."),
    "general (ALT12).bat": ("alt12", "ALT12", 41,
                            "fake + multisplit/hostfakesplit, двойной discord-фейк."),
    "general (FAKE TLS AUTO).bat": ("fake-tls-auto", "FAKE TLS AUTO", 50,
                                    "авто-фейк TLS (real+tls-mod) + multidisorder, badseq."),
    "general (FAKE TLS AUTO ALT).bat": ("fake-tls-auto-alt", "FAKE TLS AUTO ALT", 51,
                                        "авто-фейк TLS + fakedsplit, badseq (+2)."),
    "general (FAKE TLS AUTO ALT2).bat": ("fake-tls-auto-alt2", "FAKE TLS AUTO ALT2", 52,
                                         "авто-фейк TLS + multisplit seqovl, badseq (+10000000)."),
    "general (FAKE TLS AUTO ALT3).bat": ("fake-tls-auto-alt3", "FAKE TLS AUTO ALT3", 53,
                                         "авто-фейк TLS + multisplit seqovl, fooling=ts."),
    "general (SIMPLE FAKE).bat": ("simple-fake", "SIMPLE FAKE", 60,
                                  "чистые fake-пакеты, fooling=ts. Лёгкая, часто берёт Discord/YouTube."),
    "general (SIMPLE FAKE ALT).bat": ("simple-fake-alt", "SIMPLE FAKE ALT", 61,
                                      "чистый fake, fooling=badseq (+2)."),
    "general (SIMPLE FAKE ALT2).bat": ("simple-fake-alt2", "SIMPLE FAKE ALT2", 62,
                                       "чистый fake, в общем TLS-профиле max.ru вместо google."),
    "general (EXP).bat": ("exp", "EXP", 70,
                          "Экспериментальная (1.10.0): fake + multisplit со stun2-паттерном, "
                          "hostfakesplit для google, discord/stun/unknown UDP одним профилем."),
}

# .bin Flowseal -> имя blob в нашем формате.
# ACTIVE_* появились в 1.10.0: ими заменили quic_dbank в discord/stun/game-профилях.
# quic_dbank оставлен в таблице — нужен для регенерации стратегий до 1.10.0.
BLOBS = {
    "quic_initial_www_google_com.bin": "quic_google",
    "quic_initial_dbankcloud_ru.bin": "quic_dbank",
    "quic_initial_4pda.to.bin": "quic_4pda",
    "tls_clienthello_www_google_com.bin": "tls_google",
    "tls_clienthello_max_ru.bin": "tls_max",
    "tls_clienthello_4pda_to.bin": "tls_4pda",
    "stun.bin": "stun_fake",
    "stun2.bin": "stun_fake2",
    "ACTIVE_DISCORD_UDP.bin": "udp_discord",
    "ACTIVE_GAME_UDP.bin": "udp_game",
}
BLOB_FILE = {v: k for k, v in BLOBS.items()}
BASE_TLS = "tls_google"  # база для авто-фейков (fake-tls=! / только tls-mod)

SPLIT_METHODS = ("multisplit", "multidisorder", "fakedsplit", "fakeddisorder")


def extract_cmd(text: str) -> str:
    """Склейка строк-продолжений (^) и вырезка аргументов после winws.exe."""
    lines = text.splitlines()
    start_i = next(i for i, l in enumerate(lines) if "winws.exe" in l)
    buf, i = [], start_i
    while i < len(lines):
        l = lines[i].rstrip()
        cont = l.endswith("^")
        if cont:
            l = l[:-1]
        buf.append(l)
        i += 1
        if not cont:
            break
    cmd = " ".join(buf).split('winws.exe"', 1)[1]
    return cmd.replace("^", "")  # ^! -> ! (батч-экранирование)


def tokenize(cmd: str) -> list[str]:
    return [t.replace('"', "") for t in cmd.split() if t.strip()]


def split_segments(toks: list[str]) -> list[list[str]]:
    segs, cur = [], []
    for t in toks:
        if t == "--new":
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    return segs


def blob_of(val: str) -> str:
    if val == "!":
        return "!"
    if val.startswith("0x"):
        return val
    return BLOBS[val.replace("%BIN%", "")]


def path_sub(val: str) -> str:
    return val.replace("%LISTS%", "{LISTS}/")


def parse_kv(s: str) -> dict:
    out = {}
    for kv in s.split(","):
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def collect_desync(toks: list[str]) -> dict:
    d = {
        "methods": [], "repeats": None, "fooling": [], "badseq": None,
        "fake_tls": [], "fake_http": [], "fake_quic": [],
        "fake_discord": [], "fake_stun": [], "fake_unknown_udp": [],
        "tls_mod": None, "split_pos": None, "seqovl": None, "seqovl_pat": None,
        "fakedsplit_pat": None, "hostfake_mod": None, "any": False,
        "cutoff": None, "ip_id": None,
    }
    mapping = {
        "--dpi-desync-repeats": "repeats",
        "--dpi-desync-badseq-increment": "badseq",
        "--dpi-desync-fake-tls-mod": "tls_mod",
        "--dpi-desync-split-pos": "split_pos",
        "--dpi-desync-split-seqovl": "seqovl",
        "--dpi-desync-split-seqovl-pattern": "seqovl_pat",
        "--dpi-desync-fakedsplit-pattern": "fakedsplit_pat",
        "--dpi-desync-hostfakesplit-mod": "hostfake_mod",
        "--dpi-desync-cutoff": "cutoff",
        "--ip-id": "ip_id",
    }
    appends = {
        "--dpi-desync-fake-quic": "fake_quic",
        "--dpi-desync-fake-tls": "fake_tls",
        "--dpi-desync-fake-http": "fake_http",
        "--dpi-desync-fake-discord": "fake_discord",
        "--dpi-desync-fake-stun": "fake_stun",
        "--dpi-desync-fake-unknown-udp": "fake_unknown_udp",
    }
    for t in toks:
        k, _, v = t.partition("=")
        if k == "--dpi-desync":
            d["methods"] = v.split(",")
        elif k == "--dpi-desync-fooling":
            d["fooling"] = v.split(",")
        elif k == "--dpi-desync-any-protocol":
            d["any"] = True
        elif k in appends:
            d[appends[k]].append(v)
        elif k in mapping:
            d[mapping[k]] = v
    return d


def fooling_tokens(d: dict) -> list[str]:
    out = []
    for f in d["fooling"]:
        if f == "ts":
            out.append("tcp_ts=-1000")
        elif f == "md5sig":
            out.append("tcp_md5")
        elif f == "badseq":
            out.append("tcp_seq=%s" % (d["badseq"] or "-10000"))
        else:
            raise ValueError("неизвестный fooling: " + f)
    return out


def build_lua(d: dict, both: bool) -> list[str]:
    """Перевод группы --dpi-desync* профиля в строки --payload/--out-range/--lua-desync."""
    lines = []
    fool = fooling_tokens(d)
    rep = ["repeats=%s" % d["repeats"]] if d["repeats"] else []
    ipid = ["ip_id=zero"] if d["ip_id"] == "zero" else []
    methods = d["methods"]
    splitm = next((m for m in methods if m in SPLIT_METHODS), None)
    has_fake = "fake" in methods
    has_hostfake = "hostfakesplit" in methods
    has_syndata = "syndata" in methods
    payload_all = d["any"]
    rep_suffix = (":repeats=%s" % d["repeats"]) if d["repeats"] else ""

    if d["cutoff"]:
        lines.append("--out-range=-%s" % d["cutoff"])

    def fake_line(blob, with_mod):
        parts = ["fake", "blob=%s" % blob]
        if with_mod and d["tls_mod"] and d["tls_mod"] != "none":
            parts.append("tls_mod=%s" % d["tls_mod"])
        parts += fool + rep + ipid
        return "--lua-desync=" + ":".join(parts)

    def split_line():
        # multidisorder -> multidisorder_legacy: алгоритм 1:1 с nfqws1 (winws1).
        # Новый multidisorder иначе тасует сегменты на многопакетных запросах
        # (docs/manual.en.md: legacy «fully compatible with nfqws1»). Flowseal=winws1.
        lua_name = "multidisorder_legacy" if splitm == "multidisorder" else splitm
        parts = [lua_name]
        if d["split_pos"]:
            parts.append("pos=%s" % d["split_pos"])
        if splitm in ("multisplit", "multidisorder"):
            if d["seqovl"]:
                parts.append("seqovl=%s" % d["seqovl"])
                if d["seqovl_pat"]:
                    parts.append("seqovl_pattern=%s" % blob_of(d["seqovl_pat"]))
            parts += ipid  # split реальных сегментов: ip_id да, fooling/repeats НЕТ
        else:  # fakedsplit / fakeddisorder: свои фейки -> fooling+repeats
            if d["fakedsplit_pat"]:
                parts.append("pattern=%s" % blob_of(d["fakedsplit_pat"]))
            if d["seqovl"]:
                parts.append("seqovl=%s" % d["seqovl"])
                if d["seqovl_pat"]:
                    parts.append("seqovl_pattern=%s" % blob_of(d["seqovl_pat"]))
            parts += fool + rep + ipid
        return "--lua-desync=" + ":".join(parts)

    def hostfake_line():
        parts = ["hostfakesplit"]
        mod = parse_kv(d["hostfake_mod"]) if d["hostfake_mod"] else {}
        if mod.get("host"):
            parts.append("host=%s" % mod["host"])
        if mod.get("midhost"):
            parts.append("midhost=%s" % mod["midhost"])
        # altorder=1 (winws1) — у winws2 hostfakesplit аналога нет, опускаем
        parts += fool + rep + ipid
        return "--lua-desync=" + ":".join(parts)

    # --- UDP-профили (без TLS/HTTP-роутинга) ---
    # Группы копятся, а не возвращаются по первой попавшейся: с 1.10.0 в одном
    # профиле встречаются сразу discord, stun и unknown (general (EXP)), и ранний
    # выход молча терял бы всё, кроме первой группы. Порядок групп — как в .bat.
    udp: list[tuple[str, list[str]]] = []
    if d["fake_quic"]:
        udp.append(("all" if payload_all else "quic_initial",
                    [blob_of(b) for b in d["fake_quic"]]))
    if d["fake_discord"] or d["fake_stun"]:
        dbl = [blob_of(b) for b in d["fake_discord"]]
        sbl = [blob_of(b) for b in d["fake_stun"]]
        if dbl == sbl:
            udp.append(("discord_ip_discovery,stun", dbl))
        else:
            if dbl:
                udp.append(("discord_ip_discovery", dbl))
            if sbl:
                udp.append(("stun", sbl))
    if d["fake_unknown_udp"]:
        # any-protocol=1 бьёт по любому payload, без него — ровно по неопознанному
        udp.append(("all" if payload_all else "unknown",
                    [blob_of(b) for b in d["fake_unknown_udp"]]))
    if udp:
        for payload, blobs in udp:
            lines.append("--payload=%s" % payload)
            for b in blobs:
                lines.append("--lua-desync=fake:blob=%s%s" % (b, rep_suffix))
        return lines

    # --- syndata (TCP, иногда + multidisorder/multisplit) ---
    if has_syndata:
        if payload_all:
            lines.append("--payload=all")
        lines.append("--lua-desync=syndata")
        if splitm:
            lines.append(split_line())
        return lines

    # --- TCP TLS/HTTP: fake (роутинг по payload) + split/hostfake (на весь профиль) ---
    scope = "all" if payload_all else ("tls_client_hello,http_req" if both else "tls_client_hello")

    tls_entries = []  # (blob, применять_tls_mod)
    for b in d["fake_tls"]:
        if b == "!":
            tls_entries.append((BASE_TLS, True))
        elif b.startswith("0x"):
            tls_entries.append((b, False))
        else:
            tls_entries.append((blob_of(b), False))
    if not tls_entries and has_fake and d["tls_mod"] is not None:
        # fake без явного blob, но с tls-mod: авто-фейк из реального ClientHello
        tls_entries.append((BASE_TLS, d["tls_mod"] != "none"))

    last_payload = None
    block: list[str] = []  # строки после последнего --payload

    def emit_payload(p):
        nonlocal last_payload
        if p != last_payload:
            lines.append("--payload=%s" % p)
            last_payload = p
            block.clear()

    def add_fake(line):
        # при any-protocol fake-tls и fake-http попадают под один --payload=all,
        # и одинаковый блоб дал бы два идентичных фейка на пакет вместо одного
        # (в winws1 они расходились по разным протоколам). Схлопываем.
        if line in block:
            return
        block.append(line)
        lines.append(line)

    if has_fake and tls_entries:
        emit_payload("all" if payload_all else "tls_client_hello")
        for b, wm in tls_entries:
            add_fake(fake_line(b, wm))
    if has_fake and d["fake_http"]:
        emit_payload("all" if payload_all else "http_req")
        for b in d["fake_http"]:
            add_fake(fake_line(blob_of(b), False))

    if splitm or has_hostfake:
        emit_payload(scope)
        if splitm:
            lines.append(split_line())
        if has_hostfake:
            lines.append(hostfake_line())
    return lines


def profile_label(passthru: list[str], lua: list[str]) -> str:
    txt = " ".join(passthru)
    # l7 читаем значением, а не подстрокой: в 1.10.0 набор варьируется
    # (discord,stun против discord,stun,unknown), а QUIC-профиль может задаваться
    # и через --filter-l7=quic вместо --filter-udp=443.
    l7 = next((a.split("=", 1)[1] for a in passthru if a.startswith("--filter-l7=")), "")
    if "discord" in l7:
        return "Discord/STUN — голосовой UDP"
    if "{GAME_TCP}" in txt:
        return "GAME TCP (включается game-фильтром)"
    if "{GAME_UDP}" in txt:
        return "GAME UDP (включается game-фильтром)"
    has_ipset = any("--ipset=" in a for a in passthru)
    if l7 == "quic" or any(a.startswith("--filter-udp=443") for a in passthru):
        return "QUIC fallback по IP (ipset)" if has_ipset else "QUIC по hostlist"
    if "hostlist-domains=discord.media" in txt:
        return "discord.media (TCP)"
    if "list-google.txt" in txt:
        return "Google TLS (443)"
    if has_ipset:
        return "TCP fallback по IP (ipset)"
    if "--filter-l3=ipv4" in txt:
        return "Все TCP-порты (IPv4)"
    return "Общий HTTP/TLS по hostlist"


def translate_profile(seg: list[str]) -> tuple[list[str], list[str]]:
    """seg -> (passthru-аргументы фильтра/списков, строки lua-десинка)."""
    passthru, desync_toks = [], []
    filter_tcp = ""
    for t in seg:
        k, _, v = t.partition("=")
        if k.startswith("--dpi-desync") or k == "--ip-id":
            desync_toks.append(t)
            continue
        if k == "--filter-tcp":
            filter_tcp = v
            v = "{GAME_TCP}" if v == "%GameFilterTCP%" else v
        elif k == "--filter-udp":
            v = "{GAME_UDP}" if v == "%GameFilterUDP%" else v
        else:
            v = path_sub(v)
        passthru.append("%s=%s" % (k, v) if _ else k)
        # ipset-all — это реестр РКН от Flowseal; рядом с ним подключаем свой
        # ipset-user: туда winws-менеджер кладёт IP из выбранных в UI списков
        # (домены оттуда же уезжают в list-general-user.txt, который Flowseal
        # объявляет сам). Строка нужна в каждом ipset-профиле, поэтому её ставит
        # генератор — дописанная руками, она терялась бы на каждом перепорте.
        if k == "--ipset" and v.endswith("ipset-all.txt"):
            passthru.append("--ipset={LISTS}/ipset-user.txt")
    both = "80" in [p.strip() for p in filter_tcp.split(",")]
    d = collect_desync(desync_toks)
    return passthru, build_lua(d, both)


def render(bat_path: Path, meta: tuple) -> str:
    sid, name, order, desc = meta
    cmd = extract_cmd(bat_path.read_text(encoding="utf-8-sig"))
    segs = split_segments(tokenize(cmd))

    # шапка: вытащить wf из segs[0]
    wf = {}
    seg0 = []
    for t in segs[0]:
        if t.startswith("--wf-tcp="):
            wf["tcp"] = t.split("=", 1)[1]
        elif t.startswith("--wf-udp="):
            wf["udp"] = t.split("=", 1)[1]
        else:
            seg0.append(t)
    segs[0] = seg0

    def wf_line(kind):
        val = wf.get(kind, "")
        ph = "{GAME_TCP_WF}" if kind == "tcp" else "{GAME_UDP_WF}"
        var = "%GameFilterTCP%" if kind == "tcp" else "%GameFilterUDP%"
        val = val.replace("," + var, ph)
        return "--wf-%s-out=%s" % (kind, val)

    profiles = [translate_profile(s) for s in segs]

    # какие blob'ы реально используются -> объявим только их
    used = []
    for _, lua in profiles:
        for ln in lua:
            for m in re.findall(r"(?:blob|seqovl_pattern|pattern)=([A-Za-z0-9_]+)", ln):
                if m in BLOB_FILE and m not in used:
                    used.append(m)
    used.sort(key=lambda n: list(BLOBS.values()).index(n))

    out = [
        "# name: %s" % name,
        "# desc: %s" % desc,
        '# source: Flowseal "%s" -> winws2 (lua-desync). Генератор: tools/port_flowseal.py' % bat_path.name,
        "# order: %d" % order,
        "#",
        "# Один аргумент winws2 на строку. # — комментарий. Плейсхолдеры путей: {WINWS} {ASSETS} {LISTS}.",
        "# {GAME_TCP}/{GAME_UDP} — игровые профили (управляются game-фильтром),",
        "# {GAME_TCP_WF}/{GAME_UDP_WF} — игровые порты в --wf-*-out (подставляются менеджером).",
        "",
        wf_line("tcp"),
        wf_line("udp"),
        "--lua-init=@{WINWS}/lua/zapret-lib.lua",
        "--lua-init=@{WINWS}/lua/zapret-antidpi.lua",
    ]
    for b in used:
        out.append("--blob=%s:@{ASSETS}/%s" % (b, BLOB_FILE[b]))

    for i, (passthru, lua) in enumerate(profiles):
        out.append("")
        out.append("# --- профиль %d: %s ---" % (i + 1, profile_label(passthru, lua)))
        out += passthru
        out += lua
        if i < len(profiles) - 1:
            out.append("--new")
    return "\n".join(out) + "\n"


def sync_resources(src: Path) -> None:
    """Копирует fake-блобы (bin/*.bin) и хостлисты Flowseal рядом со стратегиями.

    Блобы копируем ВСЕ, а не только те, что встречаются в .bat: часть из них —
    кандидаты на подстановку в ACTIVE_*-слоты (см. modules/winws/filters.py,
    fake replace), в самих стратегиях они не упоминаются.
    """
    for src_dir, dst_dir, names in (
        (src / "bin", OUT / "assets", sorted(p.name for p in (src / "bin").glob("*.bin"))),
        (src / "lists", OUT / "hostlists", SYNC_LISTS),
    ):
        dst_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            s, d = src_dir / name, dst_dir / name
            if not s.exists():
                print("ПРОПУСК (нет в источнике): %s" % name)
                continue
            if d.exists() and d.read_bytes() == s.read_bytes():
                continue
            shutil.copyfile(s, d)
            print("СИНХР %-28s <- %s/" % (name, src_dir.name))


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.exists():
        sys.exit("Не найден репозиторий Flowseal: %s" % src)
    OUT.mkdir(exist_ok=True)
    sync_resources(src)
    for fname, meta in STRATS.items():
        bat = src / fname
        if not bat.exists():
            print("ПРОПУСК (нет файла): %s" % fname)
            continue
        text = render(bat, meta)
        (OUT / ("%s.txt" % meta[0])).write_text(text, encoding="utf-8")
        print("OK %-22s <- %s" % (meta[0] + ".txt", fname))


if __name__ == "__main__":
    main()
