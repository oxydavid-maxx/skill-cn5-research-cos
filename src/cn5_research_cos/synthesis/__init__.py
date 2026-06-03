"""P5 synthesis: the §22 decision-memo assembly (deterministic) + the LLM
synthesis brain's output wiring.

* ``blockers`` — deterministic 6-kind labeling of what is blocking the answer.
* ``memo`` — deterministic memo assembly (9 sections + blocker labels + the
  wired-in P4b citation verify/policy/flatten) over the LLM-written prose.
* ``gates`` — the four emission gates (degraded-audit / convergence / citation /
  readiness) that decide whether the memo emits.
"""
