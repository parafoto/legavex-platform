"""Поиск судебной практики для LegasVex Advocates.

Источники:
  1. kad.arbitr.ru — картотека арбитражных дел (бесплатно, неофициальный API)
  2. sudact.ru — решения судов общей юрисдикции (скрейпинг, ограниченно)

Все результаты — ссылки и краткая информация для адвоката.
Итоговый анализ практики делает AI (Ollama или OpenRouter).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    court: str
    date: str
    parties: str
    url: str
    summary: str = ""


# ---------------------------------------------------------------------------
# kad.arbitr.ru
# ---------------------------------------------------------------------------

_KAD_SEARCH_URL = "https://kad.arbitr.ru/Kad/SearchInstances"
_KAD_CASE_URL   = "https://kad.arbitr.ru/Card/{case_id}"

_KAD_HEADERS = {
    "Content-Type":   "application/json",
    "Accept":         "application/json, text/javascript, */*; q=0.01",
    "Origin":         "https://kad.arbitr.ru",
    "Referer":        "https://kad.arbitr.ru/",
    "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def _kad_build_query(keywords: list[str], count: int = 10) -> dict:
    """Build kad.arbitr.ru SearchInstances request body."""
    return {
        "Page": 1,
        "Count": count,
        "Courts": [],
        "DateFrom": None,
        "DateTo": None,
        "Sides": [],
        "Judges": [],
        "CaseNumbers": [],
        "Keywords": keywords,
        "CaseType": "",
        "ConsiderType": "",
        "WithVKS": False,
    }


def search_kad(keywords: list[str], count: int = 8) -> list[CaseResult]:
    """Search kad.arbitr.ru for cases matching keywords.

    Returns up to `count` CaseResult objects, empty list on any error.
    """
    body = json.dumps(_kad_build_query(keywords, count), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _KAD_SEARCH_URL,
        data=body,
        headers=_KAD_HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return []

    results = []
    for item in data.get("Result", {}).get("Items", []):
        case_id  = item.get("CaseId") or item.get("Id") or ""
        case_num = item.get("CaseNumber") or case_id
        court    = (item.get("Court") or {}).get("Name") or "Арбитражный суд"
        date_raw = item.get("Date") or item.get("RegDate") or ""
        date     = date_raw[:10] if date_raw else "—"

        # Build parties string
        sides = item.get("Sides") or []
        plaintiffs = [s.get("Name", "") for s in sides if s.get("Type") in ("1", 1, "Истец", "Заявитель")]
        defendants = [s.get("Name", "") for s in sides if s.get("Type") in ("2", 2, "Ответчик")]
        parties = ""
        if plaintiffs:
            parties += f"{plaintiffs[0]}"
        if defendants:
            parties += f" vs {defendants[0]}"
        if not parties and sides:
            parties = sides[0].get("Name", "")

        url = _KAD_CASE_URL.format(case_id=case_id)

        results.append(CaseResult(
            case_id=case_num,
            court=court,
            date=date,
            parties=parties,
            url=url,
        ))

    return results


# ---------------------------------------------------------------------------
# sudact.ru  (простой скрейпинг)
# ---------------------------------------------------------------------------

_SUDACT_SEARCH_URL = "https://sudact.ru/regular/search/"

_SUDACT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml",
    "Referer":    "https://sudact.ru/",
}


def search_sudact(query: str, count: int = 5) -> list[CaseResult]:
    """Search sudact.ru (общая юрисдикция). Scraping — may break without notice."""
    params = urllib.parse.urlencode({"txt": query, "page": 1})
    url = f"{_SUDACT_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers=_SUDACT_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError):
        return []

    results = []
    # Parse article/search-result blocks
    blocks = re.findall(
        r'<article[^>]*class="[^"]*search-result[^"]*"[^>]*>(.*?)</article>',
        html, re.DOTALL
    )
    for block in blocks[:count]:
        title_m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        link  = "https://sudact.ru" + title_m.group(1)
        title = re.sub(r"<[^>]+>", "", title_m.group(2)).strip()
        date_m  = re.search(r'(\d{2}\.\d{2}\.\d{4})', block)
        date    = date_m.group(1) if date_m else "—"
        court_m = re.search(r'<span[^>]*class="[^"]*court[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL)
        court   = re.sub(r"<[^>]+>", "", court_m.group(1)).strip() if court_m else "Суд общей юрисдикции"

        results.append(CaseResult(
            case_id=title[:80],
            court=court,
            date=date,
            parties="",
            url=link,
        ))

    return results


# ---------------------------------------------------------------------------
# High-level: unified search + format
# ---------------------------------------------------------------------------

def extract_keywords(topic: str) -> list[str]:
    """Extract 2-4 key legal terms from a topic description."""
    # Strip stop-words, take meaningful tokens
    stop = {
        "я", "мне", "у", "есть", "и", "в", "на", "по", "с", "от", "до",
        "что", "как", "это", "не", "но", "а", "или", "если", "то", "был",
        "была", "были", "для", "об", "за", "из", "при", "под", "над",
    }
    tokens = re.findall(r"[а-яёА-ЯЁa-zA-Z]{4,}", topic.lower())
    keywords = [t for t in tokens if t not in stop]
    # Prefer legal nouns: deduplicate and cap at 4
    seen: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.append(kw)
        if len(seen) == 4:
            break
    return seen


def search_legal_practice(topic: str) -> str:
    """Search both sources and return formatted text for the bot.

    Returns a human-readable summary with case links.
    """
    keywords = extract_keywords(topic)
    if not keywords:
        return "Не удалось извлечь ключевые слова из описания ситуации."

    kad_results    = search_kad(keywords, count=6)
    sudact_results = search_sudact(" ".join(keywords[:2]), count=4)

    lines: list[str] = [f"Судебная практика по запросу: {', '.join(keywords)}\n"]

    if kad_results:
        lines.append("Арбитражные дела (kad.arbitr.ru):")
        for r in kad_results:
            lines.append(f"• {r.case_id} | {r.court} | {r.date}")
            if r.parties:
                lines.append(f"  Стороны: {r.parties}")
            lines.append(f"  {r.url}")
        lines.append("")

    if sudact_results:
        lines.append("Суды общей юрисдикции (sudact.ru):")
        for r in sudact_results:
            lines.append(f"• {r.case_id[:70]} | {r.court} | {r.date}")
            lines.append(f"  {r.url}")
        lines.append("")

    if not kad_results and not sudact_results:
        lines.append("Дела не найдены. Попробуйте описать ситуацию конкретнее.")
    else:
        lines.append("Ссылки открываются в браузере. Проверьте актуальность решений.")

    return "\n".join(lines)
