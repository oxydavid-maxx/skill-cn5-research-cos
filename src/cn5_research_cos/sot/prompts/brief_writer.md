<!--
SOURCE ATTRIBUTION (compile step):
  Adapted from the open-deep-research (ODR) `transform_messages_into_research_topic`
  brief-writing pattern. Key borrowed principles:
    - MAXIMIZE specificity and detail: include every preference/constraint the
      user actually stated.
    - Unstated dimensions = OPEN / no-constraint. Do NOT invent or hallucinate
      constraints, scope limits, or success criteria the dialogue never raised.
    - Produce ONE precise, self-contained objective sentence (the north-star).
  Scope/field labels are adapted to the cockpit SOTBrief schema (NOT ODR's
  research-topic shape).

CONTROL NOTE: this is the ONE narrow compile call (dialogue -> SOTBrief). It runs
only AFTER the deterministic cn5_ask engine has declared convergence. The LLM
does not decide whether to compile; Python does.
-->

# SOT Brief Writer — Compile the Converged Dialogue into a SOTBrief

你會收到一段「已收斂」的釐清對話（提問者與顧問的多回合往返）。把它轉成一份精準的 Source-of-Truth 研究 brief。這份 brief 是下游所有研究與 audit 的北極星，必須精準、自洽、不漂移。

## 原則（取自 ODR transform_messages_into_research_topic）
1. **最大化具體性**：把對話中提問者「真的說過」的每一個偏好、限制、邊界都收進來。
2. **未提及的維度 = 開放 / 無限制**：對話沒談到的面向，標為開放，**不要憑空捏造**限制、範圍邊界、或成功準則。寧可留空（空陣列 / null），也不要幻覺。
3. **objective 必須是一句精準、可獨立閱讀的話**（北極星）。不要 hedging 詞。
4. **decision_criterion**：若對話明確說了準則就填；若明確被 deferred 給人類、或根本沒談，填 `null`。
5. **open_questions**：把對話結束時仍懸而未決、需要人類後續輸入的點列出來。

## 輸出（嚴格 JSON，符合提供的 SOTBrief schema，不要多餘文字）
欄位語意：
- `objective` (str, 必填)：一句話北極星目標。
- `background` (str)：脈絡。
- `in_scope` (list[str])：明確在範圍內。
- `out_of_scope` (list[str])：明確排除。
- `constraints` (list[str])：成本/時程/技術等限制（只填對話講過的）。
- `assumptions` (list[str])：研究所依賴的假設。
- `forbidden_directions` (list[str])：明確禁止的方向。
- `available_sources` (list[str])：手上有的資料來源（datasheet、內部資料…）。
- `deliverable` (str, 必填)：最終產出形式（選型表 / 一頁式 memo …）。
- `success_criteria` (list[str])：判定「夠好」的準則。
- `decision_served` (str|null)：服務誰的什麼決策。
- `decision_criterion` (str|null)：決策準則，或 null（deferred / 未談）。
- `open_questions` (list[str])：仍需人類釐清的點。

`version`、`status`、`confirmed_by`、`created_at` 由系統填寫，**你不要填**（或填預設）。
