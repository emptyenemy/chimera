"""Отчёт об автонастройке для issue на GitHub: таблица для людей и строка JSON для карты провайдеров.

Ничего не отправляется само: ссылка открывает форму нового issue с готовым текстом, человек
видит его целиком и сам решает, публиковать ли. В отчёте нет адресов, доменов и ссылок —
только номер сети, имена сервисов и вариантов, которые их починили. Из отчётов собирается
strategies/provider-map.json (tools/provider_map.py).
"""

import json
import re
from urllib.parse import urlencode

from modules.i18n import t

REPO = "emptyenemy/chimera"
TEMPLATE = "autotune-report.md"
MARK = "chimera-report"
MARK_RE = re.compile(r"<!--\s*" + MARK + r"\s+(\{.*?\})\s*-->", re.S)
URL_LIMIT = 7500   # длиннее GitHub форму не откроет; такой отчёт копируется руками
# те же семейства строк, что у `chimera fix`: причина недоступности и способ починки
REASON, VIA = "cli.fix.reason", "cli.fix.via"


def data(rec, about) -> dict:
    services = {}
    for row in (rec.get("report") or {}).get("services", []):
        if row.get("skipped"):
            continue
        fix = row.get("fix")
        services[row["name"]] = {"before": list(row["before"]["reasons"]), "ok": bool(row["after"]["ok"]),
                                 "fix": {"kind": fix["kind"], "id": fix["id"]} if fix else None}
    provider = rec.get("provider")
    return {"v": 1, "asn": provider["asn"] if provider else None, "name": provider["name"] if provider else None,
            "app": about.get("app"),
            "data": about.get("data"), "mode": rec.get("mode"), "services": services}


def build(rec, about) -> dict:
    """{"title", "text", "url", "form"}: url — форма нового issue с отчётом (None, если текст
    в адрес не влез), form — та же форма пустой, куда текст вставляется руками."""
    info = data(rec, about)
    provider = rec.get("provider")
    who = f"AS{provider['asn']} · {provider['name']}" if provider else t("msg.autotune.report.unknown_provider")
    lines = [
        f"**{t('msg.autotune.report.provider')}:** {who}",
        f"**Chimera:** {info['app']} · {t('msg.autotune.report.data')} {info['data'] or '—'} · "
        f"{t('msg.autotune.report.mode_smart') if info['mode'] == 'smart' else t('msg.autotune.report.mode_fast')}",
        "",
        f"| {t('msg.autotune.report.service')} | {t('msg.autotune.report.before')} | {t('msg.autotune.report.fix')} | "
        f"{t('msg.autotune.report.after')} |",
        "|---|---|---|---|",
    ]
    for name, row in info["services"].items():
        fix = t(f"{VIA}.{row['fix']['kind']}", id=row["fix"]["id"]) if row["fix"] else "—"
        before = ", ".join(t(f"{REASON}.{r}") for r in row["before"]) or t("msg.autotune.report.opened")
        after = t("msg.autotune.report.opened") if row["ok"] else t("msg.autotune.report.failed")
        lines.append(f"| {name} | {before} | {fix} | {after} |")
    lines += ["", t("msg.autotune.report.keep_line"),
              f"<!-- {MARK} {json.dumps(info, ensure_ascii=False, separators=(',', ':'))} -->"]
    text = "\n".join(lines)
    title = t("msg.autotune.report.title", provider=provider["name"] if provider else "?")
    url = f"https://github.com/{REPO}/issues/new?" + urlencode({"template": TEMPLATE, "title": title, "body": text})
    form = f"https://github.com/{REPO}/issues/new?" + urlencode({"template": TEMPLATE})
    return {"title": title, "text": text, "url": url if len(url) <= URL_LIMIT else None, "form": form}


def parse(body: str) -> dict | None:
    """Строка JSON из текста issue; чужой или испорченный текст — None."""
    m = MARK_RE.search(body or "")
    if not m:
        return None
    try:
        info = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(info, dict) or info.get("v") != 1 or type(info.get("asn")) is not int:
        return None
    return info if isinstance(info.get("services"), dict) else None
