"""Director repairs are deterministic code: these tests pin down the failures that used to reach the player (gaps, missing think line, one huge scene)."""

from ai_teacher_api.director import repair
from ai_teacher_api.director.run_direct import picture_problems, scene_problems
from ai_teacher_api.director.script import BoardCue, LessonScript, ScriptLine, interaction_problems, rhythm_problems, scene_spans


def line(text, *cues, pages=None):
    return ScriptLine(text=text, pages=pages or [1], cues=list(cues))


def script(*lines):
    return LessonScript(lesson_id="t", title="t", language="hi-IN", lines=list(lines))


def img(i, cap="कुल्हड़"):
    return BoardCue(kind="image", id=i, text=cap, description="d")


def card():
    return BoardCue(kind="choice", id="c1", text="प्रश्न?", options=["क", "ख", "ग"], answer_index=1)


def test_long_line_is_split_and_cues_stay_in_order():
    long = " ".join(["यह एक वाक्य है।"] * 30)
    s = script(line(long, img("a"), card()))
    assert repair.split_long_lines(s) > 0
    assert all(len(l.text.split()) <= repair.MAX_LINE_WORDS + 10 for l in s.lines)
    assert [c.kind for c in s.lines[0].cues] == ["image"]  # media with the first part
    assert [c.kind for c in s.lines[-1].cues] == ["choice"]  # card with the last part (the question is read first)


def test_card_gets_think_line_and_answer_prefix():
    s = script(line("प्रश्न पूछा जाता है?", img("a"), card()), line("यह जवाब की व्याख्या है और बहुत लंबी है इसलिए सोच की लाइन नहीं है"), line("आगे बढ़ें"))
    assert repair.repair_cards(s) >= 1
    assert s.lines[1].text == repair.THINK_LINE and s.lines[1].pages == []
    assert s.lines[2].text.startswith("उत्तर है")
    assert not [p for p in interaction_problems(s, 10, 1) if "think line" in p]


def test_new_picture_group_starts_new_scene_and_card_recalls_picture():
    s = script(line("एक", img("a")), line("दो"), line("तीन"), line("चार", img("b")), line("पाँच"), line("छह", card()), line("सोचिए..", pages=[]), line("उत्तर है — ख"))
    repair.scene_breaks(s)
    assert any(c.kind == "clear" for c in s.lines[3].cues), "a picture far from the previous one starts a scene"
    assert any(c.kind == "clear" for c in s.lines[5].cues), "the question gets its own scene"
    recalled = [c for c in s.lines[5].cues if c.kind == "image"]
    assert recalled and recalled[0].id == "b~q" and recalled[0].text == "कुल्हड़"
    assert len(scene_spans(s)) == 3


def test_adjacent_pictures_share_a_scene():
    s = script(line("एक", img("a")), line("दो", img("b")))
    assert repair.scene_breaks(s) == 0


def test_gap_points_close_every_gap():
    words = " ".join(["शब्द"] * 20)  # about 9 s per line
    s = script(line(words, BoardCue(kind="note", id="n0", text="x")), *[line(words) for _ in range(6)], line(words, BoardCue(kind="note", id="n9", text="y")))
    pts = repair.gap_points(s, 20.0)
    assert pts
    for i in pts:
        s.lines[i].cues.append(BoardCue(kind="note", id=f"g{i}", text="z"))
    assert not [p for p in rhythm_problems(s, 0, 10_000, 20.0) if "no new item" in p]


def test_restore_missing_puts_dropped_sentence_back_but_skips_options_and_aims():
    md = """## शुरुआत
![फोटो](a)
लकड़ी से कुर्सी बनती है। मिट्टी से कुल्हड़ बनता है।

सीखने का उद्देश्य: बच्चा समझेगा।

**जाँच प्रश्न 1:** कौन सा सही है?
A. पहला
B. दूसरा
[Pause]
उत्तर: B क्योंकि लकड़ी कठोर है।

## गृह कार्य
घर की चीज़ें गिनिए और लिखिए।
"""
    s = script(line("लकड़ी से कुर्सी बनती है।"), line("आगे बढ़ते हैं।"))
    restored = repair.restore_missing(md, s)
    assert restored == ["मिट्टी से कुल्हड़ बनता है।", "उत्तर: B क्योंकि लकड़ी कठोर है।"]
    assert s.lines[1].text == "मिट्टी से कुल्हड़ बनता है।"


def test_restore_never_inserts_inside_a_card_block():
    md = "पहला वाक्य यहाँ है।\n\nदूसरा नया वाक्य यहाँ है।\n"
    s = script(line("पहला वाक्य यहाँ है।", card()), line("सोचिए...", pages=[]), line("उत्तर है — ख"))
    repair.restore_missing(md, s)
    assert s.lines[1].text == "सोचिए..." and s.lines[2].text.startswith("उत्तर है")


def test_picture_problems_accept_recalls_and_flag_missing():
    md = "![x](a)\n![y](b)\n"
    ok = script(line("एक", img("a")), line("दो", img("b")), line("तीन", img("b~q")))
    assert picture_problems(md, ok) == []
    missing = script(line("एक", img("a")))
    assert any("never shown" in p for p in picture_problems(md, missing))


def test_scene_problems_flag_a_very_long_scene():
    long = " ".join(["शब्द"] * 20)
    s = script(*[line(long) for _ in range(10)])
    assert scene_problems(s)


def test_card_recalls_the_picture_named_by_its_target():
    c = card()
    c.target = "a"
    s = script(line("एक", img("a", "चीनी")), line("दो"), line("तीन"), line("चार", img("b", "लोहा")), line("पाँच"), line("छह", c), line("सोचिए..", pages=[]), line("उत्तर है — ख"))
    repair.scene_breaks(s)
    recalled = [x for x in s.lines[5].cues if x.kind == "image"]
    assert recalled and recalled[0].id == "a~q" and recalled[0].text == "चीनी"


def test_long_scene_is_cut_at_a_new_item_about_35s_in():
    w = " ".join(["शब्द"] * 20)
    s = script(*[line(w, BoardCue(kind="note", id=f"n{i}", text="x")) for i in range(14)])
    assert max(sec for _, _, sec in scene_spans(s)) > 50
    assert repair.split_long_scenes(s, 50.0) >= 1
    assert max(sec for _, _, sec in scene_spans(s)) <= 50.0


def test_question_stem_paragraph_is_not_restored():
    md = "पहला वाक्य यहाँ है।\n\nनिम्नलिखित में से कौन-सा कथन सही है?\n\nA. पहला\nB. दूसरा\n[Pause]\nउत्तर: B।\n"
    sents = repair.lecture_sentences(md)
    assert "निम्नलिखित में से कौन-सा कथन सही है?" not in sents and "पहला वाक्य यहाँ है।" in sents


def test_clear_without_a_new_item_is_moved_to_the_next_item():
    s = script(line("एक", BoardCue(kind="clear")), line("दो", BoardCue(kind="note", id="n", text="x")))
    assert repair.fix_blank_clears(s) == 1
    assert [c.kind for c in s.lines[0].cues] == [] and s.lines[1].cues[0].kind == "clear"
