"""Карта провайдеров из отчётов автонастройки: strategies/provider-map.json.

Отчёты — обсуждения (Discussions) в категории report.CATEGORY: их открывает кнопка
«Поделиться результатом» (modules/autotune/report.py). Из каждого берётся строка JSON в конце текста. Один автор
считается один раз на провайдера — по самому свежему отчёту, чтобы десяток повторов
не перевесил остальных. В карту идут только встроенные сервисы (списки из lists/):
свои списки у других пользователей не встретятся.

    python tools/provider_map.py            — собрать и записать карту
    python tools/provider_map.py --dry-run  — только показать, что получится

Карта уходит пользователям с выпуском данных (tools/release_data.py).
Нужен `gh` с входом.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.autotune import provider as provider_mod, report as report_mod  # noqa: E402

TOP = 5   # вариантов на сервис: дальше порядок перебора и так обычный
QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number body createdAt author { login } category { slug } }
    }
  }
}"""


def fetch_reports(run=subprocess.run) -> list[dict]:
    """Обсуждения категории отчётов, все страницы."""
    owner, name = report_mod.REPO.split("/")
    reports, after = [], None
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
        if after:
            args += ["-f", f"after={after}"]
        reply = json.loads(run(args, capture_output=True, text=True, encoding="utf-8", check=True).stdout)
        page = reply["data"]["repository"]["discussions"]
        reports += [node for node in page["nodes"] if (node.get("category") or {}).get("slug") == report_mod.CATEGORY]
        if not page["pageInfo"]["hasNextPage"]:
            return reports
        after = page["pageInfo"]["endCursor"]


def build(reports: list[dict], services: set[str], today: str) -> dict:
    latest = {}   # (автор, номер сети) -> отчёт
    for report in sorted(reports, key=lambda r: r.get("createdAt") or ""):
        info = report_mod.parse(report.get("body") or "")
        author = (report.get("author") or {}).get("login") or f"#{report.get('number')}"
        if info:
            latest[(author, info["asn"])] = info
    providers = {}
    for info in latest.values():
        entry = providers.setdefault(str(info["asn"]), {"names": Counter(), "reports": 0, "fixes": {}})
        entry["reports"] += 1
        if isinstance(info.get("name"), str) and info["name"]:
            entry["names"][info["name"][:80]] += 1
        for name, row in info["services"].items():
            fix = row.get("fix") if isinstance(row, dict) else None
            if (name not in services or not row.get("ok") or not isinstance(fix, dict)
                    or fix.get("kind") not in provider_mod.STEPS or not isinstance(fix.get("id"), str)):
                continue
            entry["fixes"].setdefault(name, Counter())[(fix["kind"], fix["id"][:64])] += 1
    result = {}
    for asn, entry in sorted(providers.items(), key=lambda kv: int(kv[0])):
        fixes = {name: [{"kind": k, "id": i, "n": n} for (k, i), n in counts.most_common(TOP)]
                 for name, counts in sorted(entry["fixes"].items())}
        if fixes:
            name = entry["names"].most_common(1)[0][0] if entry["names"] else ""
            result[asn] = {"name": name, "reports": entry["reports"], "services": fixes}
    return {"schema": 1, "updated": today, "providers": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    services = {p.stem for p in (ROOT / "lists").glob("*.txt")}
    data = build(fetch_reports(), services, date.today().isoformat())
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if args.dry_run:
        print(text)
        return
    path = ROOT / "strategies" / "provider-map.json"
    path.write_bytes(text.encode("utf-8"))
    print(f"записано: {path.relative_to(ROOT).as_posix()} — провайдеров {len(data['providers'])}")


if __name__ == "__main__":
    main()
