"""Lint determinístico do roteiro antes de editorial_ok (Luiz, 18/10/2026 23:22).

Rejeita, apontando a linha do roteiro.md:
- OTHER_GAME_NOT_IN_EVIDENCE: comparação/menção a outro jogo ou obra que não
  aparece na evidência verificada (memória do modelo não é fonte);
- SPECULATIVE_HEDGE: talvez, provavelmente, possivelmente, pode ser que, rumores...;
- WEEKDAY_MISMATCH / WEEKDAY_UNANCHORED: dia da semana que não bate com o
  calendário real (ou sem data/âncora para conferir);
- UNSOURCED_NUMBER / UNSOURCED_DATE: número ou data que não está na evidência
  (nem é hoje / contagem de dias derivada de hoje até uma data da evidência).
Sem modelo, sem rede: regex + calendário.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Any, Iterable

MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
WEEKDAYS = {
    "segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4,
    "sábado": 5, "sabado": 5, "domingo": 6,
}
HEDGES = (
    r"talvez", r"provavelmente", r"possivelmente", r"pode ser que", r"é possível que",
    r"rumor(?:es)?", r"boatos?", r"especula\w*", r"supostamente", r"aparentemente",
    r"ao que tudo indica", r"quem sabe", r"acredita-se", r"dizem que", r"tudo indica",
)
OTHER_TITLES = (
    r"(?:gta|grand theft auto)[\s:]*(?:v|iv|iii|ii|5|4|3|2)\b",
    r"(?:gta|grand theft auto)[\s:]+(?:san andreas|vice city stories|liberty city|chinatown wars|online)",
    r"(?:gta|grand theft auto)[\s:]+vice city\b(?!\s*,?\s*(?:eua|usa))",
    r"san andreas", r"red dead(?: redemption)?", r"\brdr\s?2?\b", r"\bbully\b", r"max payne",
    r"l\.?\s?a\.? noire", r"cyberpunk", r"elden ring", r"call of duty", r"\bfifa\b",
    r"ea sports fc", r"minecraft", r"fortnite", r"assassin'?s creed", r"the witcher",
    r"zelda", r"mafia (?:ii|iii|2|3|definitive)", r"watch dogs", r"saints row",
    r"borderlands", r"nba 2k", r"wwe 2k", r"sleeping dogs", r"scarface",
    r"bonnie (?:e|and|&) clyde", r"the last of us", r"god of war", r"spider-man",
    r"\bhalo\b", r"forza", r"starfield", r"hogwarts legacy", r"miami vice",
)
_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
    "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
    "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200,
    "duzentas": 200, "trezentos": 300, "trezentas": 300, "quatrocentos": 400,
    "quinhentos": 500, "seiscentos": 600, "setecentos": 700, "oitocentos": 800,
    "novecentos": 900,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_PT = re.compile(
    r"\b(\d{1,2})(?:º)?\s+de\s+(" + _MONTH_ALT + r")(?:\s+de\s+(\d{4}))?\b", re.I
)
_DATE_NUM = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_DATE_EN = re.compile(
    r"\b(" + "|".join(EN_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I
)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WEEKDAY_RE = re.compile(
    r"\b(segunda|terça|terca|quarta|quinta|sexta)(?:-|\s)feira\b|\b(sábado|sabado|domingo)\b",
    re.I,
)
_NUMBER_RE = re.compile(r"(?<![\w.,])(?:R\$\s?)?\d+(?:[.,]\d+)*(?![\w])", re.I)
_NUM_WORD_RE = re.compile(
    r"\b(?:(?:" + "|".join(sorted(list(_UNITS) + ["mil"], key=len, reverse=True))
    + r")(?:\s+e\s+|\s+)?)+", re.I,
)


def editorial_today() -> _dt.date:
    raw = (os.environ.get("BR_EDITORIAL_TODAY") or "").strip()
    if raw:
        return _dt.date.fromisoformat(raw)
    from zoneinfo import ZoneInfo
    return _dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def _spelled_value(run: str) -> int | None:
    words = [w for w in re.findall(r"[a-zçãéêíóôõúâ]+", run.casefold()) if w != "e"]
    if not words or any(w not in _UNITS and w != "mil" for w in words):
        return None
    total, current = 0, 0
    for word in words:
        if word == "mil":
            total += max(current, 1) * 1000
            current = 0
        else:
            current += _UNITS[word]
    return total + current


def _normalize_spelled(line: str) -> str:
    """Troca números por extenso (>=11, ou dia antes de 'de <mês>') por dígitos."""
    def repl(match: re.Match[str]) -> str:
        run = match.group(0)
        stripped = run.rstrip()
        trail = run[len(stripped):]
        value = _spelled_value(stripped)
        if value is None:
            return run
        after = line[match.end():match.end() + 16].casefold()
        is_day = bool(re.match(r"de\s+(" + _MONTH_ALT + r")", after))
        if value >= 11 or is_day:
            return f"{value}{trail}"
        return run
    return _NUM_WORD_RE.sub(repl, line)


def _resolve_year(day: int, month: int, year: int | None, today: _dt.date) -> _dt.date | None:
    try:
        if year is not None:
            return _dt.date(year if year >= 100 else 2000 + year, month, day)
        candidate = _dt.date(today.year, month, day)
        if candidate < today - _dt.timedelta(days=183):
            candidate = _dt.date(today.year + 1, month, day)
        return candidate
    except ValueError:
        return None


def _dates_in(text: str, today: _dt.date) -> list[tuple[int, int, _dt.date | None, tuple[int, int]]]:
    found = []
    for m in _DATE_PT.finditer(text):
        day, month = int(m.group(1)), MONTHS[m.group(2).casefold()]
        year = int(m.group(3)) if m.group(3) else None
        found.append((day, month, _resolve_year(day, month, year, today), m.span()))
    for m in _DATE_NUM.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            continue
        year = int(m.group(3)) if m.group(3) else None
        found.append((day, month, _resolve_year(day, month, year, today), m.span()))
    for m in _DATE_EN.finditer(text):
        day, month, year = int(m.group(2)), EN_MONTHS[m.group(1).casefold()], int(m.group(3))
        found.append((day, month, _resolve_year(day, month, year, today), m.span()))
    for m in _DATE_ISO.finditer(text):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12:
            found.append((day, month, _resolve_year(day, month, year, today), m.span()))
    return found


def _values(token: str) -> set[float]:
    clean = re.sub(r"R\$\s?", "", token, flags=re.I).strip()
    out: set[float] = set()
    for candidate in (clean.replace(".", "").replace(",", "."), clean.replace(",", "")):
        try:
            out.add(round(float(candidate), 4))
        except ValueError:
            pass
    return out


def _evidence_texts(evidence: Iterable[Any]) -> list[str]:
    texts = []
    for item in evidence:
        if isinstance(item, dict):
            text = str(item.get("statement") or item.get("text") or "")
        else:
            text = str(item or "")
        if text.strip():
            texts.append(text)
    return texts


def _strip_dates(text: str, today: _dt.date) -> str:
    spans = sorted((d[3] for d in _dates_in(text, today)), reverse=True)
    for start, end in spans:
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def lint_script(
    text: str,
    *,
    evidence: Iterable[Any] | None,
    today: _dt.date | None = None,
) -> list[dict[str, Any]]:
    today = today or editorial_today()
    corpus_list = _evidence_texts(evidence) if evidence is not None else None
    corpus = "\n".join(corpus_list or ()).casefold()
    norm_corpus = _normalize_spelled(corpus)

    allowed_dates: set[tuple[int, int]] = {(today.day, today.month)}
    allowed_numbers: set[float] = {float(today.day), float(today.month), float(today.year)}
    evidence_dates = _dates_in(norm_corpus, today)
    for day, month, resolved, _span in evidence_dates:
        allowed_dates.add((day, month))
        allowed_numbers.update({float(day), float(month)})
        if resolved is not None:
            allowed_numbers.add(float(resolved.year))
            delta = (resolved - today).days
            if delta >= 0:
                allowed_numbers.update({float(delta), float(delta // 7)})
    for token in _NUMBER_RE.findall(_strip_dates(norm_corpus, today)):
        allowed_numbers.update(_values(token))

    findings: list[dict[str, Any]] = []
    scene = 0
    for line_no, raw_line in enumerate(str(text or "").split("\n"), start=1):
        line = raw_line.strip()
        if not line:
            continue
        scene += 1
        folded = line.casefold()

        def add(code: str, match: str) -> None:
            findings.append({
                "code": code, "line": line_no, "scene": scene,
                "match": match, "text": line[:300],
            })

        for pattern in HEDGES:
            for m in re.finditer(r"(?<!\w)" + pattern + r"(?!\w)", folded):
                add("SPECULATIVE_HEDGE", line[m.start():m.end()])

        for pattern in OTHER_TITLES:
            for m in re.finditer(pattern, folded):
                if re.search(pattern, corpus):
                    continue
                add("OTHER_GAME_NOT_IN_EVIDENCE", line[m.start():m.end()])

        normalized = _normalize_spelled(line)
        dates = _dates_in(normalized, today)
        for m in _WEEKDAY_RE.finditer(normalized):
            named = (m.group(1) or m.group(2)).casefold()
            expected = WEEKDAYS[named]
            anchor = None
            if dates:
                nearest = min(dates, key=lambda d: abs(d[3][0] - m.start()))
                anchor = nearest[2]
            elif re.search(r"\bhoje\b", normalized, re.I):
                anchor = today
            elif re.search(r"\bamanhã\b|\bamanha\b", normalized, re.I):
                anchor = today + _dt.timedelta(days=1)
            elif re.search(r"\bontem\b", normalized, re.I):
                anchor = today - _dt.timedelta(days=1)
            if anchor is None:
                add("WEEKDAY_UNANCHORED", m.group(0))
            elif anchor.weekday() != expected:
                add("WEEKDAY_MISMATCH", f"{m.group(0)} ≠ {anchor.isoformat()}")

        if corpus_list is None:
            continue
        for day, month, resolved, (start, end) in dates:
            if (day, month) not in allowed_dates:
                add("UNSOURCED_DATE", normalized[start:end])
            elif resolved is not None and re.search(r"\d{4}", normalized[start:end]) and \
                    float(resolved.year) not in allowed_numbers:
                add("UNSOURCED_DATE", normalized[start:end])
        scrubbed = re.sub(r"\bgta\s*6\b", " ", _strip_dates(normalized, today), flags=re.I)
        for m in _NUMBER_RE.finditer(scrubbed):
            if not (_values(m.group(0)) & allowed_numbers):
                add("UNSOURCED_NUMBER", m.group(0))
    return findings


def format_findings(findings: list[dict[str, Any]], *, limit: int = 20) -> str:
    return "; ".join(
        f"L{f['line']} {f['code']} «{f['match']}» :: {f['text'][:160]}"
        for f in findings[:limit]
    )
