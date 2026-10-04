"""Что проверять у сервиса: адреса из его списка и контрольные сайты.

Hosts-подмена работает только для дословно перечисленных имён (поддоменов в hosts нет),
поэтому проверочные адреса — всегда точные записи списка. Для встроенных списков
порядок задан заранее: главная страница и API, которые отвечают на HTTPS; для своих
списков берутся первые домены. `www.` списки отбрасывают (это тот же сайт), поэтому
здесь его тоже нет.
"""

from modules import domains

# Контрольные сайты из разных сетей: российский, на Cloudflare и Microsoft — чтобы контроль
# работал и там, где ya.ru заблокирован (Украина) или режут Cloudflare. Охраняются только те,
# что открывались до подбора; если перестали — вариант сломал интернет.
CANARY = ("ya.ru", "example.com", "microsoft.com")
MAX_TARGETS = 3

CURATED = {
    "youtube": ("youtube.com", "i.ytimg.com", "youtubei.googleapis.com"),
    "discord": ("discord.com", "gateway.discord.gg", "cdn.discordapp.com"),
    "openai": ("chatgpt.com", "api.openai.com", "openai.com"),
    "anthropic": ("claude.ai", "api.anthropic.com", "anthropic.com"),
    "google-gemini": ("gemini.google.com", "aistudio.google.com", "generativelanguage.googleapis.com"),
    "telegram": ("telegram.org", "web.telegram.org", "api.telegram.org"),
    "x": ("x.com", "api.x.com", "abs.twimg.com"),
    "meta": ("instagram.com", "facebook.com", "cdninstagram.com"),
    "threads": ("threads.net", "threads.com"),
    "netflix": ("netflix.com", "nflxext.com"),
    "spotify": ("open.spotify.com", "api.spotify.com", "accounts.spotify.com"),
    "twitch": ("twitch.tv", "gql.twitch.tv"),
    "linkedin": ("linkedin.com",),
    "whatsapp": ("web.whatsapp.com", "whatsapp.com"),
    "signal": ("signal.org", "chat.signal.org"),
    "notion": ("notion.so", "api.notion.com"),
    "deepl": ("deepl.com",),
    "grok": ("grok.com", "x.ai"),
    "microsoft-copilot": ("copilot.microsoft.com",),
    "viber": ("viber.com",),
    "torrents": ("rutracker.org", "nnmclub.to"),
}


def exact_domains(entries) -> list[str]:
    """Домены списка как их читают модули: без ссылок, IP, подсетей и дублей."""
    seen = []
    for raw in entries:
        entry = domains.normalize_entry(raw).lower().strip(".")
        if entry and domains.as_network(entry) is None and "." in entry and entry not in seen:
            seen.append(entry)
    return seen


def targets(name: str, entries) -> list[str]:
    exact = exact_domains(entries)
    chosen = [d for d in CURATED.get(name, ()) if d in exact]
    for domain in exact:
        if len(chosen) >= MAX_TARGETS:
            break
        if domain not in chosen:
            chosen.append(domain)
    return chosen[:MAX_TARGETS]
