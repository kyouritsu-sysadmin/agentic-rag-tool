"""Canonicalize structured metadata before storage, authorization and retrieval."""

import unicodedata
from .org import (
    COMPANY_ALIASES,
    DEPT_ALIASES,
    SECTION_ALIASES,
    DOC_TYPE_ALIASES,
    COMPANY_ID,
    DEPTS,
    SECTIONS,
    ORG_CHART,
)

MAPPINGS = dict(
    company=COMPANY_ALIASES, dept=DEPT_ALIASES, section=SECTION_ALIASES, doc_type=DOC_TYPE_ALIASES
)


def canonical(field, value):
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value).strip()
    return next(
        (
            target
            for alias, target in MAPPINGS[field]
            if unicodedata.normalize("NFKC", alias).casefold() == value.casefold()
        ),
        value,
    )


def valid_scope(company, dept, section):
    # Other explicitly configured tenants may define their own taxonomy.
    if company not in COMPANY_ID:
        return True
    if dept and dept not in DEPTS[company]:
        return False
    if section and section not in SECTIONS[company]:
        return False
    if dept and section:
        parents = {
            row["dept"]
            for row in ORG_CHART[COMPANY_ID[company]].values()
            if row["section"] == section
        }
        if parents and dept not in parents:
            return False
    return True
