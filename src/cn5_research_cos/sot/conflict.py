"""PURE deterministic conflict detection on a SOTBrief.

`detect(brief, change)` returns a `Conflict` when a proposed change CONTRADICTS
the current Source-of-Truth, or `None` when it merely fills in an unset field or
adds a non-contradicting item. The clarifier NEVER silently overwrites — a
returned Conflict is surfaced to the human for an explicit decision.

NO LLM, NO I/O, NO datetime.now(): a pure function of (brief, change) so it is
fully unit-testable on hand-built pairs.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .brief import SOTBrief


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Conflict(BaseModel):
    field: str
    sot_value: Any
    new_value: Any
    source: str = ""
    severity: Severity


# Fields whose change is a direction-redefining, high-severity contradiction.
_HIGH_SEVERITY_SCALARS = {"objective", "deliverable", "decision_criterion", "decision_served"}

# Scope / direction list fields where a direct contradiction is high severity.
_SCOPE_LIST_FIELDS = {"in_scope", "out_of_scope", "forbidden_directions"}

# The complementary field used to detect in/out-of-scope contradictions.
_SCOPE_COMPLEMENT = {
    "in_scope": "out_of_scope",
    "out_of_scope": "in_scope",
}


def _scalar_conflict(field: str, sot_value: Any, new_value: Any, source: str) -> Conflict | None:
    # Filling an unset (None / empty) value is never a conflict.
    if sot_value in (None, ""):
        return None
    if new_value == sot_value:
        return None
    severity = Severity.high if field in _HIGH_SEVERITY_SCALARS else Severity.medium
    return Conflict(field=field, sot_value=sot_value, new_value=new_value,
                    source=source, severity=severity)


def _list_conflict(brief: SOTBrief, field: str, new_list: list[Any], source: str) -> Conflict | None:
    sot_list = list(getattr(brief, field) or [])
    new_set = set(map(str, new_list))
    sot_set = set(map(str, sot_list))

    # Dropping a previously-stated constraint/assumption = relaxation (medium).
    removed = sot_set - new_set
    if field in ("constraints", "assumptions") and removed:
        return Conflict(field=field, sot_value=sot_list, new_value=new_list,
                        source=source, severity=Severity.medium)

    # A scope item that directly contradicts the complementary scope list
    # (e.g. adding X to in_scope when X is already in out_of_scope) = high.
    comp = _SCOPE_COMPLEMENT.get(field)
    if comp is not None:
        added = new_set - sot_set
        comp_set = set(map(str, getattr(brief, comp) or []))
        clash = added & comp_set
        if clash:
            return Conflict(field=field, sot_value=sot_list, new_value=new_list,
                            source=source, severity=Severity.high)

    # forbidden_directions: dropping a forbidden direction = high (re-opening a
    # path the SOT explicitly closed).
    if field == "forbidden_directions" and removed:
        return Conflict(field=field, sot_value=sot_list, new_value=new_list,
                        source=source, severity=Severity.high)

    # Pure additions of non-contradicting items are fill-ins, not conflicts.
    return None


def detect(brief: SOTBrief, change: dict[str, Any], source: str = "") -> Conflict | None:
    """Return the first Conflict between ``brief`` and a proposed ``change`` dict.

    ``change`` maps field name -> proposed new value. Only the fields present in
    ``change`` are checked. Returns None when the change is non-contradicting
    (fill-in or compatible addition).
    """
    for field, new_value in change.items():
        if not hasattr(brief, field):
            continue
        sot_value = getattr(brief, field)
        if isinstance(sot_value, list) or field in _SCOPE_LIST_FIELDS or field in (
            "constraints",
            "assumptions",
        ):
            new_list = new_value if isinstance(new_value, list) else [new_value]
            c = _list_conflict(brief, field, new_list, source)
        else:
            c = _scalar_conflict(field, sot_value, new_value, source)
        if c is not None:
            return c
    return None
