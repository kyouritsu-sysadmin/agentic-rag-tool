"""Deterministic scope resolution; no implicit default company or year clamping."""

import re
import unicodedata
from datetime import date
from itertools import product
from kyoritsu_backend.core.errors import ApplicationError
from kyoritsu_backend.schemas.retrieval import Period
from kyoritsu_backend.schemas.retrieval import RetrievalRequest
from kyoritsu_backend.core.auth import Principal, require_company
from .org import COMPANY_ALIASES, DEPT_ALIASES, DOC_TYPE_ALIASES, SECTION_ALIASES
from .taxonomy import valid_scope


def aliases(query: str, mapping: list[tuple[str, str]]) -> list[str]:
    masked = query
    found = []
    for alias, canonical in sorted(mapping, key=lambda x: len(x[0]), reverse=True):
        if alias in masked:
            if canonical not in found:
                found.append(canonical)
            masked = masked.replace(alias, " " * len(alias))
    return found


def extract_periods(query: str) -> list[Period]:
    query = unicodedata.normalize("NFKC", query)
    pairs: list[tuple[int | None, int | None]] = []
    year = None
    used = False
    for match in re.finditer(r"(?P<year>\d{4})年|(?P<month>\d{1,2})月", query):
        if match["year"]:
            if year is not None and not used:
                pairs.append((year, None))
            year, used = int(match["year"]), False
        else:
            pairs.append((year, int(match["month"])))
            used = True
    if year is not None and not used:
        pairs.append((year, None))
    return [Period(year=y, month=m) for y, m in dict.fromkeys(pairs)]


def plan(request: RetrievalRequest, principal: Principal) -> list[dict]:
    q = unicodedata.normalize("NFKC", request.query)
    companies = [request.company] if request.company else aliases(q, COMPANY_ALIASES)
    for company in companies:
        require_company(principal, company)
    # Unspecified companies are explicitly scoped to the authenticated caller.
    companies = companies or list(principal.companies)
    depts = [request.dept] if request.dept else aliases(q, DEPT_ALIASES) or [None]
    sections = [request.section] if request.section else aliases(q, SECTION_ALIASES) or [None]
    kinds = [request.doc_type] if request.doc_type else aliases(q, DOC_TYPE_ALIASES) or [None]
    periods = request.periods or extract_periods(q) or [Period()]
    if request.year is not None or request.month is not None:
        periods = [
            Period(
                year=request.year if request.year is not None else p.year,
                month=request.month if request.month is not None else p.month,
            )
            for p in periods
        ]
    meeting_dates = (
        [request.meeting_date]
        if request.meeting_date
        else [date.fromisoformat(s) for s in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", q)] or [None]
    )
    scopes = []
    for company, dept, section, period, kind, meeting in product(
        companies, depts, sections, periods, kinds, meeting_dates
    ):
        if not valid_scope(company, dept, section):
            continue
        scope = dict(
            company=company,
            dept=dept,
            section=section,
            doc_type=kind,
            year=period.year,
            month=period.month,
            meeting_date=meeting,
        )
        if scope not in scopes:
            scopes.append(scope)
    if not scopes:
        raise ApplicationError(422, "Filters do not describe a valid organization scope")
    if len(scopes) > 24:
        raise ApplicationError(422, "Query requests too many scopes; split the comparison")
    return scopes
