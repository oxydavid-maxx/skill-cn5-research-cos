import cn5_research_cos.brains.synthesis as syn
from cn5_research_cos.llm import sdk_client


def test_default_model_is_sonnet():
    assert sdk_client.DEFAULT_MODEL == "claude-sonnet-4-6"


def test_synthesizer_uses_opus(monkeypatch):
    captured = {}

    def fake_call(system, user, schema, *, model=None, **kw):
        captured["model"] = model
        return {k: "" for k in syn.ALL_OUTPUT_KEYS}

    monkeypatch.setattr(syn, "call_structured", fake_call)
    from cn5_research_cos.models import ResearchState

    syn.RealSynthesizer().write_sections(ResearchState(run_id="r", original_question="q"))
    assert captured["model"] == "claude-opus-4-8"
