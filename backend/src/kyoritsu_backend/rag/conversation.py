"""Branch-local follow-up resolution; explicit entities and topic resets win."""

import re
import unicodedata
from .planning import aliases, extract_periods
from .org import COMPANY_ALIASES, DEPT_ALIASES, SECTION_ALIASES, DOC_TYPE_ALIASES
from kyoritsu_backend.schemas.retrieval import RetrievalRequest
from kyoritsu_backend.schemas.retrieval import Period

FOLLOWUP = re.compile(
    r"それ|その|同じ|引き続き|では|については|what about|and (?:in|for)|same", re.I
)
RESET = re.compile(r"話題を変|別の話|新しい話題|new topic|change (?:the )?topic", re.I)


def contextual_request(history, no_rerank=True, previous=None):
    """Replay supplied user turns, or extend the persisted parent request.

    The stored request makes context independent of the answer history window,
    process lifetime, and which branch was selected most recently.
    """
    state = RetrievalRequest.model_validate(previous) if previous else None
    for message in history:
        if message["role"] != "user":
            continue
        query = unicodedata.normalize("NFKC", message["content"])
        inherit = bool(state and FOLLOWUP.search(query) and not RESET.search(query))
        fields = {}
        for field, mapping in [
            ("company", COMPANY_ALIASES),
            ("dept", DEPT_ALIASES),
            ("section", SECTION_ALIASES),
            ("doc_type", DOC_TYPE_ALIASES),
        ]:
            values = aliases(query, mapping)
            if len(values) == 1:
                fields[field] = values[0]
            elif not values and inherit:
                fields[field] = getattr(state, field)
        # A changed company/department must not inherit an incompatible child scope.
        if inherit and fields.get("company") != state.company:
            for field, mapping in [("dept", DEPT_ALIASES), ("section", SECTION_ALIASES)]:
                if not aliases(query, mapping):
                    fields.pop(field, None)
        elif inherit and fields.get("dept") != state.dept and not aliases(query, SECTION_ALIASES):
            fields.pop("section", None)
        periods = extract_periods(query)
        old_periods = state.periods if inherit else None
        if not periods:
            periods = old_periods
        elif old_periods and all(p.year is None for p in periods):
            years = {p.year for p in old_periods}
            if len(years) == 1:
                periods = [Period(year=old_periods[0].year, month=p.month) for p in periods]
        state = RetrievalRequest(
            query=query, periods=periods or None, no_rerank=no_rerank, **fields
        )
    if state is None:
        raise ValueError("A user message is required")
    return state
