"""Vendored Albert contract + cheap-LLM Albert simulator (cockpit Auditor).

`contract.py` is vendored from `skill-cn5-i-am-albert/albert/cockpit_contract.py`
(the `to_audit_result` producer-side mapping) and adapted to be self-contained
in this repo and to construct THIS repo's `AuditResult` / `AlbertChallenge`
Pydantic models 1:1. `albert_challenge.schema.json` is vendored verbatim from
`skill-cn5-i-am-albert/schemas/`. P3/P6 swap the simulator for the real external
skill at the SAME contract.
"""
from .contract import to_audit_result
from .simulator import RealAlbertSimulator

__all__ = ["to_audit_result", "RealAlbertSimulator"]
