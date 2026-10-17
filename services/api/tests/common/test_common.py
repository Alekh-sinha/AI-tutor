import json

from ai_teacher_api.common import logsetup
from ai_teacher_api.common.paths import public_id, split_public_id


def test_public_ids_roundtrip():
    assert public_id("ch6", "lesson-2") == "lesson-2-v2"
    assert public_id("ch7", "lesson-2") == "ch7-lesson-2-v2"
    assert split_public_id("lesson-2-v2") == ("ch6", "lesson-2")
    assert split_public_id("ch7-lesson-2-v2") == ("ch7", "lesson-2")
    assert split_public_id("lesson-3") == ("ch6", "lesson-3")


def test_feature_log_writes_jsonl_and_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(logsetup, "LOG_DIR", tmp_path)
    log = logsetup.FeatureLog("director")
    log.info("hello", text="x" * 9000, n=1)
    rec = json.loads((tmp_path / "director.jsonl").read_text().splitlines()[0])
    assert rec["event"] == "hello" and rec["feature"] == "director" and len(rec["text"]) < 6100 and rec["n"] == 1
