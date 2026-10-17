from ai_teacher_api.live.board import offset_of, sentences


def test_sentence_offsets_index_into_the_transcript():
    said = "नमस्ते बच्चों. आज हम घर्षण सीखेंगे। क्या तुमने देखा है?खेत में हल चलता है."
    parts = sentences(said)
    assert [t for _, t in parts] == ["नमस्ते बच्चों.", "आज हम घर्षण सीखेंगे।", "क्या तुमने देखा है?", "खेत में हल चलता है."]
    for off, text in parts:
        assert said[off:].startswith(text)  # the client shows a note when its caption has reached this character
    assert offset_of(parts, 0) == 0 and offset_of(parts, 99) == parts[-1][0] and offset_of([], 3) == 0
