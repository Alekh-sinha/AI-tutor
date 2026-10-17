from ai_teacher_api.live import boardstate

PICS = {"p1_marble": "/chat/class-1/p1_marble.webp", "p2_brick": "/chat/class-1/p2_brick.webp"}
FIGS = {"f1_forces": {"html": "<div class=\"fig\">x</div>", "caption": "बल", "step": "s"}}


def test_empty_board_says_so_and_lists_unused_material():
    s = boardstate.describe([], PICS, FIGS, set())
    assert s.startswith("Board now: EMPTY")
    assert "p1_marble" in s and "p2_brick" in s and "f1_forces" in s


def test_board_items_and_used_material():
    board = [{"type": "note", "style": "heading", "text": "घर्षण बल"}, {"type": "image", "src": PICS["p1_marble"], "caption": "गोली"}, {"type": "figure", "name": "f1_forces"}]
    s = boardstate.describe(board, PICS, FIGS, {"p1_marble", "f1_forces"})
    assert 'heading "घर्षण बल"' in s and "picture p1_marble" in s and "figure f1_forces" in s
    assert "Prepared, not shown yet: p2_brick" in s


def test_used_but_cleared_is_not_listed_as_unused():
    s = boardstate.describe([], PICS, FIGS, {"p1_marble", "p2_brick", "f1_forces"})
    assert s == "Board now: EMPTY"
