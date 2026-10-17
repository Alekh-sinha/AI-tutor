from ai_teacher_api.common.plaintext import has_latex, plain


def test_latex_becomes_unicode():
    assert plain(r"$$4\text{Al} + 3\text{O}_2 \rightarrow 2\text{Al}_2\text{O}_3$$") == "4Al + 3O₂ → 2Al₂O₃"
    assert plain(r"$$\text{धातु (Metal)} + \text{ऑक्सीजन} \rightarrow \text{ऑक्साइड}$$") == "धातु (Metal) + ऑक्सीजन → ऑक्साइड"


def test_plain_text_unchanged():
    assert not has_latex("4Al + 3O₂ → 2Al₂O₃ — सादा पाठ")
    assert plain("सादा पाठ → ठीक") == "सादा पाठ → ठीक"
