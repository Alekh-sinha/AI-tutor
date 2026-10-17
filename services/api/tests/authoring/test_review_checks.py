from pathlib import Path

from PIL import Image

from ai_teacher_api.authoring.edit_loop import Findings, combine
from ai_teacher_api.authoring.review import PictureAudit, attention_gaps, lecture_checks


def pic(i, ok=False):
    return PictureAudit(id=i, seen="s", matches=ok, problem="p", fix="f")


def test_picture_finding_needs_every_pass_text_is_union():
    f = combine(Findings(), [(["[critic] concept 1: a. Fix: x"], [pic("p1"), pic("p2")]), (["[critic] concept 2: b. Fix: y"], [pic("p1")])], {"p1", "p2"}, 2)
    assert list(f.pictures) == ["p1"] and list(f.doubtful) == ["p2"]
    assert len(f.text) == 2


def test_picture_issue_in_text_channel_is_dropped():
    f = combine(Findings(), [(["[critic] p1: bad. Fix: x"], []), (["[critic] picture p1: bad. Fix: x"], [])], {"p1"}, 2)
    assert f.text == []


def test_attention_gap_counted_in_code():
    md = "![a](a)\n" + " ".join(["शब्द"] * 250) + "\n![b](b)\n"
    assert len(attention_gaps(md)) == 1
    assert attention_gaps("![a](a)\n" + " ".join(["शब्द"] * 100) + "\n![b](b)\n") == []


def test_unused_and_missing_pictures_and_length(tmp_path: Path):
    for n in ("used", "spare"):
        Image.new("RGB", (8, 8)).save(tmp_path / f"{n}.webp")
    md = "![d](used)\n![e](ghost)\n" + " ".join(["शब्द"] * 1300)
    issues = " ".join(lecture_checks(md, tmp_path, 1))
    assert "spare" in issues and "never drawn" in issues and "ghost" in issues and "at most" in issues


def test_archive_unused_moves_but_never_deletes(tmp_path: Path):
    from ai_teacher_api.authoring.edit_loop import archive_unused

    for n in ("used", "spare"):
        Image.new("RGB", (8, 8)).save(tmp_path / f"{n}.webp")
    assert archive_unused(tmp_path, "![d](used)") == ["spare"]
    assert (tmp_path / "unused" / "spare.webp").exists() and (tmp_path / "used.webp").exists()
