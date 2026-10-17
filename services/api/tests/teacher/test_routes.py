import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_teacher_api.teacher import routes


def make_lesson(tmp_path: Path) -> Path:
    d = tmp_path / "illustrated" / "lesson-1-final"
    d.mkdir(parents=True)
    (d / "lecture.md").write_text("पहला पैराग्राफ।\n\nदूसरा पैराग्राफ।\n")
    return d


def test_diff_is_per_paragraph():
    d = routes._diff("एक\n\nदो\n\nतीन", "एक\n\nदो बदला\n\nतीन")
    assert d == [{"before": "दो", "after": "दो बदला"}]


def test_snapshot_then_undo_restores_text_and_pictures(tmp_path, monkeypatch):
    d = make_lesson(tmp_path)
    (d / "a.webp").write_bytes(b"old")
    routes._snapshot(d, "before change")
    (d / "lecture.md").write_text("बदला हुआ")
    (d / "a.webp").write_bytes(b"new")
    monkeypatch.setattr(routes, "_dir", lambda lesson, chapter: d)
    monkeypatch.setattr(routes, "_view", lambda lesson, chapter: {"ok": True})
    routes.undo("lesson-1", "ch6")
    assert (d / "lecture.md").read_text().startswith("पहला") and (d / "a.webp").read_bytes() == b"old"
    with pytest.raises(HTTPException):
        routes.undo("lesson-1", "ch6")  # snapshot consumed


def test_auth_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("TEACHER_TOKEN", "s3cret")
    with pytest.raises(HTTPException):
        routes.auth("wrong")
    routes.auth("s3cret")
    monkeypatch.delenv("TEACHER_TOKEN")
    routes.auth(None)  # development mode


def test_bad_ids_are_rejected():
    with pytest.raises(HTTPException):
        routes._dir("../etc", "ch6")
    with pytest.raises(HTTPException):
        routes.chapter_dir("../../x")


def test_files_mount_serves_pictures_only(tmp_path):
    from fastapi.testclient import TestClient

    from ai_teacher_api import app as appmod

    c = TestClient(appmod.app)
    assert c.get("/files/ch6/source.pdf").status_code == 404
    assert c.get("/files/ch6/illustrated/lesson-1-final/lecture.md").status_code == 404
    assert c.get("/files/ch6/illustrated/lesson-1-final/../../plan.json").status_code in (404, 400)
