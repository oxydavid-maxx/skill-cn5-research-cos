# Phase 5d — honest debate visibility (3 guarantees, mirror Albert) (design)

> 2026-06-03. SUPERSEDES the earlier "un-suppressable / 100%-to-screen" framing, which a peer review correctly refuted: writing to a device handle (CONOUT$/`/dev/tty`) is NOT a visibility guarantee — it fails when (1) no terminal exists (CI/cron/service/headless/harness), (2) a pty wrapper (script/winpty/tmux) owns the terminal, (3) the human watches captured stdout (harness/web/SSH-piped), and it fights the user's legitimate output capture. The only un-breakable invariant is **content persisted to a file**. This spec adopts the honest model that the (red-teamed) `skill-cn5-i-am-albert` already uses (`albert/deliberation.py` + `run_albert.py::_redirect_refusal`). Builds on P5b (`StageReporter`). DoD: the three guarantees below hold under an HONEST red-team that REPORTS what breaks (breaking is the correct result).

## What we DO guarantee (the three honest guarantees)
1. **Durable artifact = the only real 100%.** Every per-stage debate block (incl. Albert's full output) is written to **`runs/<run_id>/debate.md`**, flushed per block, **fail-CLOSED** (a write failure raises a `VisibilityContractError` — for an audit-driven cockpit, no auditable record ⇒ do not proceed). Survives EVERY redirect / pipe / background / no-tty / pty / harness case because it does not depend on a screen existing.
2. **Best-effort live = real terminal sees it.** Each block also goes to **flushed `sys.stderr` with forced UTF-8** (`PYTHONIOENCODING`/`reconfigure(encoding="utf-8")`). Any real foreground terminal shows it live, no mojibake. (stderr, not stdout, so the deliverable on stdout stays clean.)
3. **Detect-and-refuse = can't ACCIDENTALLY hide it.** At startup, if neither stdout nor stderr is an interactive TTY → **refuse to run (exit 2)** with a clear "請在終端機跑；若確需非互動執行,加 `--allow-redirect`" message. Escapes: `--allow-redirect`, a cockpit/embedded flag, and `CN5_COS_ALLOW_REDIRECT=1`. With an escape, the run proceeds and the durable file still has everything. Mirrors `run_albert.py::_redirect_refusal`.

## What we DO NOT guarantee (stated honestly, no overclaim)
- Pixels on a screen that **doesn't exist** (headless) — impossible; nobody can.
- Defeating a **hostile pty wrapper** or a user who **chose `--allow-redirect`** — they own/elected the channel.
- We will NOT use language like "100% / invincible / nothing can block it." The guarantee is **content-never-lost + can't-accidentally-hide + real-terminal-live**, not "guaranteed pixels."

## Optional bonus (fail-SILENT, never the guarantee)
A best-effort extra write to `CONOUT$` (Windows) / `/dev/tty` (POSIX) IF it opens — helps the "piped-but-also-watching in a real terminal" case (`cos run | tee log`). **Fail-silent**; never relied on; never breaks the user's `> log`.

## `cos watch <run_id>`
A tiny command that tails `runs/<run_id>/debate.md` (built-in `tail -f` equivalent) so a colleague watches with ONE command, no knowledge of tail/paths. The notification email + `cos run` startup line print the `debate.md` path + this command.

## Modules
- `observability/reporter.py`: `StageReporter` gains a durable-file sink (`runs/<id>/debate.md`, fail-closed) + stderr (flush+UTF-8) + optional fail-silent tty bonus; the passed-stream stays for back-compat.
- `observability/guard.py`: `refuse_if_hidden(streams, *, allow_redirect, embedded) -> None|exit2` (mirror `_redirect_refusal`).
- `cli.py`: call the guard at `run`/`run-auto` start (honor `--allow-redirect` / `CN5_COS_ALLOW_REDIRECT`); print the `debate.md` path; add `cos watch <run_id>`.

## Tests / DoD — HONEST red-team (reports what breaks; breaking = correct)
- **Durable artifact (the 100%):** under EVERY form — `> file`, `| cat`, `2>&1`, `> NUL`/`/dev/null`, background `&`, non-tty subprocess (stdin/out/err = pipes), AND a pty wrapper — `runs/<id>/debate.md` contains the full debate incl. Albert blocks. (Deterministic mock-loop; assert the file, not the screen.)
- **Refuse (can't accidentally hide):** a non-tty subprocess invocation EXITS 2 with the guidance, UNLESS `--allow-redirect`/env; with the escape it runs + the file is complete. (Spawn via subprocess with pipes; assert exit 2 + message; assert escape works.)
- **Live stderr:** in a (simulated) tty, blocks appear on stderr, flushed, UTF-8 (no mojibake) — assert via a captured stderr + an interactive-tty fake.
- **Honesty ledger in the test/report:** explicitly record which adversaries are DEFENDED (file always; accidental-hide refused) vs NOT DEFENDED (no-screen-exists; hostile-pty; chosen --allow-redirect) — and assert the code/docs contain NO "100%/invincible/nothing can block" language (a structural grep test).
- **Regression:** P1–P5c stay green (the StageReporter change defaults to the durable sink + stderr; existing tests that passed a StringIO stream still work).
- **Manual (I run on this box):** `cos run-auto ... > NUL 2>&1` (with `--allow-redirect`) → the run refuses without the flag; with it, `debate.md` is complete; a foreground run shows the debate on stderr. Report honestly.
- Committed; push on user confirmation.

## Wording fix (everywhere)
Replace any "un-suppressable / 100% to screen / red-team proves nothing can block it" with the three honest guarantees above. (The MRC running in parallel will produce the global prevention for the overclaim pattern itself.)
