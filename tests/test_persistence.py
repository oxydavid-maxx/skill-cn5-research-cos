import pytest
from cn5_research_cos.store import new_run, save_snapshot, load_snapshot


def test_round_trip(tmp_path):
    s = new_run("q", run_id="r1", now="2026-06-01T00:00:00"); s.iteration_count = 2
    save_snapshot(s, base_dir=tmp_path)
    assert load_snapshot("r1", base_dir=tmp_path) == s


def test_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot("nope", base_dir=tmp_path)
