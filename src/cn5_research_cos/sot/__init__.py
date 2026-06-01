"""SOT (Source-of-Truth) clarification front-end (Phase 2a).

Configures the reusable `cn5_ask` iterate-until-converged engine with a narrow
per-turn LLM step (Socratic clarifying questions + C1-C4 signal assessment) and
a compile step (dialogue -> SOTBrief), then adds the SOT lifecycle
(persist / version / supersede / conflict-surface) around the engine's output.

The loop / convergence / stop / routing is NOT reimplemented here — it lives in
`cn5_ask` (deterministic). P2a only supplies the narrow LLM + the SOT lifecycle.
"""
