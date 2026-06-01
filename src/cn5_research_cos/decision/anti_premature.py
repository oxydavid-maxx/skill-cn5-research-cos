"""Anti-premature 7-checklist (R2).

A terminal_stop / synthesize cannot be taken until ALL seven prerequisites are
true. The graph's anti_premature node sets these flags as nodes run; cos_decision
AND-s ``all_done(prereqs)`` into terminal eligibility so a fresh state can never
terminal-stop on iteration 1.
"""
from __future__ import annotations

PREREQS = [
    "broad_expansion",            # issue_expansion ran a broad pass
    "albert_audit_ran",           # the Albert auditor actually ran
    "counterargument_pass",       # skeptic produced counterarguments
    "source_confidence_checked",  # source_critic reviewed evidence
    "pending_questions_extracted",  # audit extracted next questions
    "blockers_classified",        # residual blockers classified addressable/residual
    "explicit_continue_explanation",  # an explicit reason recorded for stop/continue
]


def all_done(flags: dict) -> bool:
    return all(flags.get(k, False) for k in PREREQS)
