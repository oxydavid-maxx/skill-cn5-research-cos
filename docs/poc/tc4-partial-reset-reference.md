# BASELINE dogfood — TC4 partial reset: a general guiding design rule

> Saved 2026-06-03. **This is the STANDING BASELINE question for skill-cn5-research-cos** (user directive 2026-06-03: "把這個題目當作未來的 baseline"). Re-run the cockpit on this SAME question as it matures (each phase) to measure progress against a fixed real BU research target. First real run: **after P4b** ("p4b 完成後就跑看看"). Use the user's prior research below as REFERENCE INPUT (P4a internal-doc consume) AND as the QUALITY BAR the cockpit's output must reach or challenge. Source: user's prior research session (pasted 2026-06-03), grounded in TC4Dx UM v1.1 Ch.37 SMM + two RDC papers.
>
> **Baseline protocol:** keep this question + the established findings below FROZEN. Each cockpit run is logged (date, phase, what it reached/challenged, where it fell short) so improvement is measurable run-over-run. Do NOT edit the established findings to match cockpit output — that would defeat the baseline.

## The research question (what the cockpit must produce)
**Find a general guiding design rule that lets us implement TC4-style partial (selective module) reset in our own Gateway/Zonal SoC.** Output = a crisp, reusable design rule + the boundary conditions, not MRD boilerplate.

## Established findings (the user's prior research — the bar to reach/challenge)

### TC4 partial reset = two capabilities (NOT one reset type)
- **Module Reset** — resets a single IP **kernel** only; the **BPI/config (bus slave) shell is NOT reset**; `RST_STAT` reports done; no effect outside the module. (TC4Dx UM v1.1, Ch.37.3.4.3, p.6354.)
- **Module Group Reset (MGR)** — **4 configurable groups** (membership via `RST_CTRLA.GRSTENx`); triggered by **ESR0/1/2, SMU SAFE0/SAFE1/SMUSEC, software, STMx compare-match**; resets all modules in the group together = **application-partition recovery**. No MGR for CPUs (CPU1+ have individual module reset, but don't join MGR groups). (Ch.37.3.4.4, p.6356–6358; Fig.829 application partitioning.)
- **Exempt from module reset (the boundary)**: PMS/SMM/SCU/CCU/CSCU/VMT/WTU, SMU/Error-pins, NVM/PFLASH/DFLASH, NVMR/PRRAM/DRRAM, LMU, IR, SRI/FPI/LLI, CPU0, CPUcs, CSS/PKC/TRNG. (Table 1647, p.6355.) **Rule: the more shared (bus backbone / interrupt router / shared memory / safety-manager / boot-CPU / security-root / power-reset infra), the less it can be locally reset.**
- FFI relation: partial reset gives **fault-reaction containment**, NOT full FFI (FFI still needs memory/DMA/interrupt/timing/peripheral interference analysis).

### SOTA per-module reset design = class-based local recovery wrapper (NOT one reset wire)
Core principle: **separate the bus/config SHELL (stays alive, accessible) from the IP KERNEL (locally reset/cleared/re-init'd)**; quiesce → drain → isolate → clear → re-init → verify → release → report. Matches TC4's "kernel reset, BPI not reset."

**Recovery Class table (the user's framework — an internal DD checklist, NOT a TC4 term):**
| Class | IP type | Required mechanism | TC4 confidence |
|---|---|---|---|
| R0 | simple slave | kernel reset + status | high |
| R1 | configurable peripheral | shell/BPI alive + config retain/reload + kernel reset | high |
| R2 | FIFO/stream | block-new + drain/drop + pointer/valid/credit clear | med (per-IP chapter) |
| R3 | bus master/DMA | quiesce + outstanding drain/abort + error attribution + master-id preserve | med-high (DMA per-channel reset) |
| R4 | safety output | safe-state clamp + SW revalidation before release | med (PORTS/eGTM/SMU) |
| R5 | power-gated | LPC/UPF isolation + retention + power ack (separate FSM) | not module reset — own track |

### RDC / isolation insight (from "Four Steps To Resolving Reset Domain Crossing…" + a 2nd RDC paper)
- Instead of output-gating ("gate outputs to 0 before asserting reset" — fragile, must know each output's safe idle value), **use a standard interface handshake** (e.g. AXI-Stream `tvalid`/`tready`) as the isolation boundary: the protocol's idle semantics define safe isolation, so you don't reason per-signal. **Input matters as much as output** — a standard interface covers both.
- Reset flow for Module A behind such isolation: **`iso_en=1` → assert reset → `iso_en=0`**.

## What "good cockpit output" looks like (dogfood success criteria)
1. Independently reaches (or improves on) the **shell-alive / kernel-reset / class-based wrapper** principle + the **shared-infra-exempt boundary**.
2. The **guiding rule** is general (applies beyond TC4) and states the boundary condition explicitly.
3. Albert genuinely challenges weak spots (e.g. "partial reset ≠ FFI"; "R2/R3 drain/quiesce not provable from the SMM summary alone — needs per-IP evidence"; "RRC is not an industry-standard block name").
4. Every normative claim is citation-backed (TC4 UM page / a real RDC paper), verbatim-verified — the citation-discipline P4b enforces.
5. Internal-doc evidence (TC4 UM) consumed via the P4a paperwork path; web/SOTA via the researcher.

## Cockpit readiness note
As of 2026-06-03 the cockpit runs P1–P4a (audit loop + web + internal-doc). **P4b (convergence engine + two-altitude ranking + citation discipline) is being built; P5 (synthesis/final memo) is still a stub.** Run this POC **after P4b** ("p4b 完成後就跑看看" — user 2026-06-03); a polished final-memo deliverable additionally needs P5.
