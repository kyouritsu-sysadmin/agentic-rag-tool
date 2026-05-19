import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.org import (
    COMPANY_ALIASES, DEFAULT_COMPANY,
    DEPT_ALIASES, SECTION_ALIASES, DOC_TYPE_ALIASES,
)
from config.keywords import KEYWORDS

# ─── Regex ────────────────────────────────────────────────────────────────────

_RE_MEETING_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RE_YEAR = re.compile(r"(202[3-6])年")

# Ordered longest-first to prevent "1月" matching inside "11月"/"12月"
_MONTH_KANJI = [
    ("12月", 12), ("11月", 11), ("10月", 10),
    ("1月",   1), ("2月",   2), ("3月",   3),
    ("4月",   4), ("5月",   5), ("6月",   6),
    ("7月",   7), ("8月",   8), ("9月",   9),
]
_RE_MONTH_NUM = re.compile(r"(1[0-2]|[1-9])月")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _all_matches(query: str, mapping: list[tuple[str, str]]) -> list[str]:
    """Return all canonical values whose alias appears in query (deduped, order preserved)."""
    seen, result = set(), []
    for alias, canonical in mapping:
        if alias in query and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _extract_periods(query: str) -> list[tuple[int, int]]:
    """
    Extract all (year, month) pairs from query.
    Full ISO date takes priority. Then scans for year+month kanji combinations.
    Returns list of unique (year, month) tuples in order of appearance.
    """
    periods: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    # Full ISO dates first
    for m in _RE_MEETING_DATE.finditer(query):
        y, mo = int(m.group(1)[:4]), int(m.group(1)[5:7])
        if (y, mo) not in seen:
            seen.add((y, mo))
            periods.append((y, mo))

    if periods:
        return periods

    # Find all years and all months mentioned
    years  = [int(m.group(1)) for m in _RE_YEAR.finditer(query)]
    months = []
    # Kanji months: scan longest-first, blank out matched spans so shorter
    # patterns (e.g. "2月") cannot re-match inside already-consumed text ("12月")
    masked = list(query)
    for kanji, num in _MONTH_KANJI:
        idx = 0
        s = "".join(masked)
        while True:
            pos = s.find(kanji, idx)
            if pos == -1:
                break
            months.append((pos, num))
            # blank out matched span in masked so shorter keys won't re-match
            for i in range(pos, pos + len(kanji)):
                masked[i] = " "
            s = "".join(masked)
            idx = pos + len(kanji)
    # Numeric fallback only if no kanji found
    if not months:
        for m in _RE_MONTH_NUM.finditer(query):
            months.append((m.start(), int(m.group(1))))

    months_ordered = [num for _, num in sorted(months)]
    months_deduped = list(dict.fromkeys(months_ordered))

    if not months_deduped:
        return []

    if not years:
        # No year in query — return month-only periods as (None, month)
        return [(None, mo) for mo in months_deduped]

    if len(years) == 1:
        # Single year applies to all months
        y = years[0]
        for mo in months_deduped:
            if (y, mo) not in seen:
                seen.add((y, mo))
                periods.append((y, mo))
    else:
        # Multiple years: pair by position order
        for i, mo in enumerate(months_deduped):
            y = years[i] if i < len(years) else years[-1]
            if (y, mo) not in seen:
                seen.add((y, mo))
                periods.append((y, mo))

    return periods


def _keyword_lookup(query: str, company: str | None) -> tuple[str | None, str | None]:
    """
    Scan query for keywords in KEYWORDS map.
    Returns (dept, section) from first match consistent with company.
    """
    for kw, meta in KEYWORDS.items():
        if kw not in query:
            continue
        kw_company = meta["company"]
        # Skip if keyword belongs to a different company
        if kw_company and company and kw_company != company:
            continue
        dept    = meta["dept"]
        section = meta["section"]
        if dept or section:
            return dept, section
    return None, None


# ─── Main pass ────────────────────────────────────────────────────────────────

def taxonomy_pass(user_query: str) -> dict:
    """
    Extract structured filters from a natural language query.

    Returns:
        {
          "companies":     list[str],               # always >= 1
          "depts":         list[str],               # empty if none found
          "sections":      list[str],               # empty if none found
          "doc_types":     list[str],               # empty if none found
          "periods":       list[tuple[int|None, int]],  # (year, month) pairs
          "meeting_dates": list[str],               # ISO dates if present
        }
    """
    if not user_query:
        raise ValueError("Empty query supplied to taxonomy_pass().")

    # Companies
    companies = _all_matches(user_query, COMPANY_ALIASES)
    if not companies:
        companies = [DEFAULT_COMPANY]

    company = companies[0]  # primary company for keyword resolution

    # Depts — taxonomy aliases first
    depts = _all_matches(user_query, DEPT_ALIASES)

    # Sections — taxonomy aliases first
    sections = _all_matches(user_query, SECTION_ALIASES)

    # 薄物 ambiguity: no number → resolve by company
    if not sections and "薄物" in user_query:
        sections = ["薄物2課" if company == "共立電照" else "薄物1課"]

    # Keyword lookup — only if taxonomy found nothing for dept/section
    if not depts and not sections:
        kw_dept, kw_section = _keyword_lookup(user_query, company)
        if kw_dept:
            depts = [kw_dept]
        if kw_section:
            sections = [kw_section]

    # Doc types
    doc_types = _all_matches(user_query, DOC_TYPE_ALIASES)

    # Periods (year, month pairs)
    periods = _extract_periods(user_query)

    # Meeting dates (ISO)
    meeting_dates = [m.group(1) for m in _RE_MEETING_DATE.finditer(user_query)]

    return {
        "companies":     companies,
        "depts":         depts,
        "sections":      sections,
        "doc_types":     doc_types,
        "periods":       periods,
        "meeting_dates": meeting_dates,
    }
