# BU Research Cockpit 流程圖（文字版）

> **Canonical flow + HITL numbering (H0–H6).** User-provided 2026-06-01; colleague-shareable. This is the authoritative end-to-end flow for `skill-cn5-research-cos`. The HITL model here (H0–H6) supersedes the earlier 6-gate framing in `human-steering-layer.md` (which is now the explanatory companion).
>
> **REVISION R2 (2026-06-01):** after reading the actual source of GPT Researcher + Open Deep Research and the internal `paperwork` plugin (see `gap-audit-2026-06-01.md`), the loop gains a **scope→brief front-end**, a **supervisor with parallel context-isolated research workers**, a **compression node**, **two-level iteration caps**, **branch-budget decay**, an explicit **anti-premature 7-checklist**, and **interrupt()-based HITL**. The colleague-facing diagram below keeps the simple shape; the engineering shape is in the "Revised engineering flow (R2)" section at the bottom + `gap-audit-2026-06-01.md`.

```text
會議中出現回答不了的問題
    ↓
Intake
輸入：原始問題、會議背景、誰問的、目標 audience、已知限制
    ↓
[H0 人力介入] Preflight
確認：
- 這次目標是 meeting defense / decision readiness / 找 blockers？
- 預設研究 priority 是什麼？
- 有哪些資料可用？
- 遇到人不回覆時，AI 要怎麼 fallback？
    ↓
初始化三個活 artifacts
    ↓
Dynamic Issue Map          用來探索問題空間、unknown unknowns
    +
Albert Challenge Map       用來模擬 Albert 會怎麼挑戰
    +
Research Readiness Board    用來管理 answered / pending / blocked
    ↓
進入 Continuous Convergence Loop
```

## 主 Loop：AI 自動研究 + Albert audit

```text
Chief-of-Staff Agent 選最高價值 issue / branch
    ↓
Research Plan            決定這輪要查什麼、驗證什麼、反駁什麼
    ↓
Research Worker          ODR / GPT Researcher / OpenAI Deep Research API / Internal RAG / stub worker
    ↓
Evidence Bundle          claims / sources / confidence / conflicts / missing evidence
    ↓
Source Critic            檢查 source quality、citation strength、marketing bias
    ↓
Skeptic Agent            找反方、替代解釋、目前答案弱點
    ↓
Albert Thought Agent     用 Albert 的角度 audit：
                         - Albert 會挑戰哪裡？
                         - 哪裡不夠 business-ready？
                         - 有沒有 premature conclusion？
                         - 有沒有只是在寫長報告，但沒有回答 decision？
    ↓
Artifact Update          Dynamic Issue Map / Albert Challenge Map / Research Readiness Board / Human Task Queue
    ↓
Readiness Scoring        Albert Challenge / Decision / Research Exhaustion / Human Bottleneck Clarity
    ↓
Iteration Summary        本輪新增什麼？Albert 會挑戰什麼？哪些已答 / 還 pending / 需要人？下一輪建議？
    ↓
Chief-of-Staff Decision  判斷下一步
```

## Decision Router：loop 的核心

```text
Chief-of-Staff Decision
    ↓
還有高價值研究方向       → continue research → 回「選最高價值 issue / branch」
發現新方向               → branch → 建立新 issue branch → 回 Dynamic Issue Map
人類改變目標(如「Albert care 的是 ROI」) → rerank → 重排既有 evidence → 回 Dynamic Issue Map
需要方向判斷             → [H1] Pull Direction → 人選方向 → 記錄 Steering Event → 回 Dynamic Issue Map
需要 Albert / BU owner 決策 → [H2] Call External Decision → 拿到 decision criterion → 回 Dynamic Issue Map
需要文件 / 資料 / source validation → [H3] Push Human Task → 人去拿資料；AI 同時研究其他沒 blocked 的 branch
人類中途插話改方向       → [H4] Ad-hoc Steering → 記錄 Steering Event → branch 或 rerank → 回 Dynamic Issue Map
AI 卡住且資訊不足繼續     → [H5] Call Help → 列最小必要輸入 → 等人回覆或用 fallback 繼續
外部研究邊際效益低       → synthesize → 進入整理模式
readiness 達標           → terminal stop
```

## Human-in-loop 具體在哪裡？

```text
H0. Preflight              開始前確認 mission、priority、fallback。
H1. Pull Direction         方向分歧時，AI 拉人選方向。
H2. Call External Decision  需要 Albert / BU owner 選 decision criterion 時停下來。
H3. Push Human Task         需要人下載文件、提供內部資料、驗證 source 時，AI 指派任務。
H4. Ad-hoc Steering         人類隨時可以插話改方向，系統記錄並 branch / rerank。
H5. Call Help               AI 遇到 hard blocker，列出最小必要輸入。
H6. Final Review            最後 memo 送出前，人類確認是否可用。
```

## 三個主要 Loop

**Loop 1 — AI Research Loop**
```text
選 issue → research → evidence → source critic → skeptic → Albert audit
→ update artifacts → readiness scoring → decision → 不夠就回去選下一個 issue
```
用途：讓 AI 自己持續研究、反駁、audit，不是跑一次就結束。

**Loop 2 — Human Steering Loop**
```text
AI 發現方向分歧 / 需要 BU preference / 需要 decision
→ pull human → 人類選方向 → 記錄 steering event → 更新 issue map → 重新進入 research loop
```
用途：避免 AI 亂猜 BU context，也避免人類一直被開放式問題打擾。

**Loop 3 — Push Human Help Loop**
```text
AI 發現缺文件 / 缺內部資料 / 缺 source validation
→ 建立 human task(owner / 需要資料 / why needed / blocking question)
→ AI 繼續研究其他 branch → 人類補資料回來 → 回到 evidence bundle → 繼續 audit / update / scoring
```
用途：讓「缺資料」變成明確任務，而不是一句模糊的「需要更多 research」。

## 最後輸出

```text
Synthesis Mode
    ↓
Final Memo
- Executive Answer
- Albert Challenge Map
- What We Can Say Now
- What We Cannot Say Yet
- What Is Blocking Us
- Required Human Decisions / Inputs
- Evidence Summary
- Risks and Assumptions
- Recommended Next Action
- Appendix
    ↓
[H6 人力介入] Final Review
    ↓
Done
```

## 一句話版

```text
會議問題
→ 建立 Issue Map / Challenge Map / Readiness Board
→ AI 研究 → Albert 角色 audit → 更新 artifacts → 判斷是否夠好
→ 不夠就繼續研究、branch、rerank、pull human 或 push human
→ 直到達到 readiness，或剩下都變成明確 human blockers
→ 產出 final memo
```

---

## Revised engineering flow (R2) — grounded in GPT Researcher + Open Deep Research + paperwork

```text
intake
 → scope (clarify gate; H0)                         [ODR clarify_with_user]
 → write_brief  (compressed "north star" objective) [ODR write_research_brief]
 → issue_expansion (grounded: cheap search first)   [GPTR grounded decomposition]
 → SUPERVISOR / select_branch                        [ODR supervisor]
     └─ fan-out N context-isolated workers (concurrency cap):   [ODR/GPTR asyncio.gather + cap]
          research_worker → source_critic(cheap rank) → compress(cited summary)
          · research_worker adapters (§16): stub | GPT-Researcher | ODR |
            paperwork topic-report (INTERNAL datasheet/doc survey) | internal-RAG
 → skeptic / counterargument
 → albert_audit  (typed exit: clean | challenges)    [GPTR reviewer null-exit]
 → artifact_update (consume COMPRESSED output; dedup) [ODR compress + override_reducer]
 → readiness_scoring (+ plateau detector)
 → anti_premature_checklist (the 7 prerequisites, §10)
 → cos_decision (staged binary gates: audit-clean? → readiness-met? →
                 budget-left? → human-needed?; exhaustion + emission-gate; branch-budget decay)
 → router: continue | branch | rerank | pull_human(interrupt) |
           push_human(interrupt) | synthesize | pause | terminal_stop
```

### Citation / evidence discipline (borrowed from internal `paperwork`, by intent)
Every claim in an EvidenceBundle must: (1) carry a **resolvable citation** to a primary source; (2) if quoted, match the source **verbatim ≥0.85** (anti-fabrication); (3) declare the source **role** (primary/secondary/standard/marketing/internal); (4) record **coverage-gaps** — sources checked that yielded nothing become a first-class auditable record (not a silent omission); (5) **flatten to primary source** — downstream never cites a sibling worker's digest, only originals. Document handling: `reference/pdf/` (originals) + `reference/fragments/` (docling-converted MD) + a `reference-map` registry; **structural provenance, NOT embedding/RAG**, is the citation source-of-truth.
