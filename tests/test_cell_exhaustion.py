from cn5_research_cos.decision import cell_exhaustion as ce
from cn5_research_cos.models import TaskCell, CellStatus


def _cell(): return TaskCell(id="NXP|f", vendor="NXP", spec_group="f", objective="o",
                             success_criteria=["packet_buffer", "vlan_table"])


def test_not_exhausted_when_field_missing_and_modalities_left():
    assert ce.public_exhausted(_cell(), filled={"packet_buffer"}, modalities_tried={"search"},
                               all_modalities={"search", "fetch", "extract"}, rounds_no_new=0) is False


def test_exhausted_when_all_modalities_tried():
    assert ce.public_exhausted(_cell(), filled={"packet_buffer"}, modalities_tried={"search", "fetch", "extract"},
                               all_modalities={"search", "fetch", "extract"}, rounds_no_new=0) is True


def test_classify_covered():
    assert ce.classify_cell(_cell(), filled={"packet_buffer", "vlan_table"}, gated_detected=False) == CellStatus.covered


def test_classify_needs_internal_when_gated():
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=True) == CellStatus.blocked  # = needs_internal


def test_classify_na_public_exhausted():
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=False) == CellStatus.partial
    assert ce.classify_cell(_cell(), filled=set(), gated_detected=False) == CellStatus.na
