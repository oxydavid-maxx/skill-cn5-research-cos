"""P8 H0 — generates Socratic clarification questions for the missing criteria.
The cockpit ASKS; the human ANSWERS. Cheap (haiku) — question-gen, no reasoning depth."""
from __future__ import annotations

from ..llm.sdk_client import call_structured
from ..models import ResearchState

_PROMPTS = {
    "purpose": "這份研究的用途是什麼？要拿來做什麼決定？(RFQ評分 / 選型 / 投資 / 定義參考…)",
    "scope":   "範圍邊界：哪些 in、哪些 out？(例：只比 silicon 規格，不含 gateway 應用分類)",
    "success": "你要的交付長怎樣？哪張表、哪些欄位最關鍵？",
    "constraints": "約束：NDA / 只能公開源 / 時間或深度上限？以及你手上有什麼可放進 reference 的素材？",
}


class MockClarifier:
    def ask(self, state: ResearchState, missing: list[str]) -> list[str]:
        return [_PROMPTS[m] for m in missing if m in _PROMPTS]


_SCHEMA = {"type": "object",
           "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
           "required": ["questions"], "additionalProperties": False}
_SYSTEM = ("You are a research chief-of-staff running a SOCRATIC clarification. "
           "Ask 1-3 targeted questions to pin ONLY the missing criteria. You ASK; "
           "the human ANSWERS — never answer for them. Traditional Chinese, terms untranslated. "
           "Return strict JSON {\"questions\": [...]}.")


class RealClarifier:
    def ask(self, state: ResearchState, missing: list[str]) -> list[str]:
        seed = "\n".join(f"- {m}: {_PROMPTS.get(m, '')}" for m in missing)
        user = (f"原始問題：{state.original_question}\n目前 brief：{state.research_brief or '(無)'}\n"
                f"還沒釘死的項目：\n{seed}\n針對這些缺項問出精準的蘇格拉底問題。")
        raw = call_structured(_SYSTEM, user, _SCHEMA, model="haiku")
        return [str(q) for q in raw.get("questions", []) if q]
