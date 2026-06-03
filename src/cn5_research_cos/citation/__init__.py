"""Citation discipline (P4b Component 3), SPLIT by source origin.

* ``verify`` — deterministic claim->source verification, routed by origin:
  web claims run our difflib >= 0.85 verbatim check; internal claims are carried
  as paperwork-verified (no difflib re-run).
* ``policy`` — the tiered escalation (unverified -> reverify -> human / flag) +
  flatten-to-primary (reject a claim that cites a digest, not a primary Source).
"""
from . import policy, verify

__all__ = ["verify", "policy"]
