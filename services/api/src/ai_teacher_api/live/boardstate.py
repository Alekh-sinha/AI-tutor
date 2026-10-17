"""What the teacher can SEE: a plain snapshot of the board and of the prepared material she has not used yet. She cannot look at the children's screen, and without this she does not know what is showing (seen 2026-10-16:
she cleared the board before every question and left prepared pictures unused). Only status, no commands and no timings: she decides what to update. Sent with every tool answer and after every turn of hers (session.py)."""


def describe(board: list[dict], pictures: dict[str, str], figures: dict[str, dict], used: set[str]) -> str:
    """board = the elements shown now; pictures = {name: src} and figures = {name: {...}} prepared; used = names she has already shown at some point."""
    shown = []
    shown_pics: set[str] = set()
    shown_figs: set[str] = set()
    for e in board:
        t = e.get("type")
        if t == "note" and e.get("style") == "pending":
            shown.append("a picture being drawn")
        elif t == "note":
            shown.append(f'{"heading" if e.get("style") == "heading" else "note"} "{e.get("text", "")}"')
        elif t == "image":
            name = next((n for n, src in pictures.items() if src == e.get("src")), "")
            shown_pics.add(name)
            shown.append(f"picture {name or 'drawn in class'}" + (f' ("{e["caption"]}")' if e.get("caption") else ""))
        elif t == "figure":
            shown_figs.add(e.get("name", ""))
            shown.append(f"figure {e.get('name', '')}")
    line = "Board now: " + ("; ".join(shown) if shown else "EMPTY")
    unused = [n for n in list(pictures) + list(figures) if n not in used and n not in shown_pics and n not in shown_figs]
    return line + ("\nPrepared, not shown yet: " + ", ".join(unused) if unused else "")
