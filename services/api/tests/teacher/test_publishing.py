import json

import pytest

from ai_teacher_api.teacher import publishing


@pytest.fixture()
def world(tmp_path, monkeypatch):
    pub = tmp_path / "public"
    for sub in ("lessons", "audio", "img"):
        (pub / sub).mkdir(parents=True)
    monkeypatch.setattr(publishing, "WEB_PUBLIC", pub)
    d = tmp_path / "ch"
    d.mkdir()
    return pub, d


def put_live(pub, pid, text):
    (pub / "lessons" / f"{pid}.json").write_text(json.dumps({"audio": f"/audio/{pid}.mp3", "img": f"/img/{pid}-i1.webp", "t": text}))
    (pub / "audio" / f"{pid}.mp3").write_bytes(b"live-audio")
    (pub / "img" / f"{pid}-i1.webp").write_bytes(b"live-img")


def test_unpublished_lesson_builds_into_the_live_id(world):
    pub, d = world
    assert publishing.build_id(d, "lesson-1-v2") == "lesson-1-v2"
    assert publishing.status(d, "lesson-1-v2", "md", "{}")["live"] is False


def test_published_lesson_builds_a_hidden_draft_and_publish_copies_it(world):
    pub, d = world
    put_live(pub, "lesson-1-v2", "old")
    (d / "directed-lesson-1-v2.json").write_text('{"v":1}')
    publishing.mark_published(d, "lesson-1-v2", "lecture", '{"v":1}')
    assert publishing.build_id(d, "lesson-1-v2") == "lesson-1-v2-draft"
    st = publishing.status(d, "lesson-1-v2", "lecture", '{"v":1}')
    assert st["live"] and st["version"] == 1 and not st["video_changed"] and not st["lecture_changed"]

    # the teacher edits the video: a draft is built, students still see the old one
    put_live(pub, "lesson-1-v2-draft", "new")
    (d / "directed-lesson-1-v2.json").write_text('{"v":2}')
    st = publishing.status(d, "lesson-1-v2", "lecture", '{"v":2}')
    assert st["video_changed"] and st["draft_ready"] and not st["lecture_changed"]
    assert json.loads((pub / "lessons" / "lesson-1-v2.json").read_text())["t"] == "old"

    publishing.publish_draft(d, "lesson-1-v2")
    live = json.loads((pub / "lessons" / "lesson-1-v2.json").read_text())
    assert live["t"] == "new" and live["audio"] == "/audio/lesson-1-v2.mp3" and live["img"] == "/img/lesson-1-v2-i1.webp"
    assert (pub / "img" / "lesson-1-v2-i1.webp").read_bytes() == b"live-img"
    new = publishing.mark_video_published(d, "lesson-1-v2", '{"v":2}')
    assert new["version"] == 2 and not (pub / "lessons" / "lesson-1-v2-draft.json").exists()


def test_discard_returns_the_working_script_to_live(world):
    pub, d = world
    put_live(pub, "lesson-1-v2", "old")
    (d / "directed-lesson-1-v2.json").write_text('{"v":1}')
    publishing.mark_published(d, "lesson-1-v2", "lecture", '{"v":1}')
    put_live(pub, "lesson-1-v2-draft", "new")
    (d / "directed-lesson-1-v2.json").write_text('{"v":2}')
    publishing.discard_draft(d, "lesson-1-v2")
    assert (d / "directed-lesson-1-v2.json").read_text() == '{"v":1}'
    assert not (pub / "lessons" / "lesson-1-v2-draft.json").exists()


def test_lecture_change_is_detected(world):
    pub, d = world
    put_live(pub, "lesson-1-v2", "old")
    publishing.mark_published(d, "lesson-1-v2", "lecture one", "{}")
    assert publishing.status(d, "lesson-1-v2", "lecture two", "{}")["lecture_changed"]
