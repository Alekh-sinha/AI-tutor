"""LaTeX -> plain Unicode text. The models sometimes write chemistry as LaTeX ($$\\text{Al}_2\\text{O}_3 \\rightarrow ...$$); the voice would read the
backslashes aloud and the board would show raw markup. Used as the LAST guard (director repair, TTS); the lecture checks also flag it so the author fixes the source."""

import re

SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
SUP = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
SYMBOLS = {r"\rightarrow": "→", r"\to": "→", r"\longrightarrow": "→", r"\Rightarrow": "⇒", r"\leftrightarrow": "↔", r"\rightleftharpoons": "⇌", r"\uparrow": "↑",
           r"\downarrow": "↓", r"\times": "×", r"\cdot": "·", r"\degree": "°", r"\circ": "°", r"\Delta": "Δ", r"\%": "%", r"\,": " ", r"\;": " ", r"\ ": " "}
LATEX = re.compile(r"\$|\\[A-Za-z]+|\\[%,; ]|_\{|\^\{")


def has_latex(text: str) -> bool:
    return bool(LATEX.search(text))


def _script(m: re.Match, table: dict) -> str:
    body = m.group(2) if m.group(2) is not None else m.group(3)
    return body.translate(table)


def plain(text: str) -> str:
    """Convert LaTeX markup to Unicode (subscripts, arrows). Text without LaTeX is returned unchanged."""
    if not has_latex(text):
        return text
    t = text.replace("$$", "").replace("$", "")
    for _ in range(3):  # \text{..}, \mathrm{..}, \textbf{..} (nested braces are rare)
        t = re.sub(r"\\(?:text|mathrm|textbf|mathbf|mathit|textit)\s*\{([^{}]*)\}", r"\1", t)
    for k in sorted(SYMBOLS, key=len, reverse=True):
        t = t.replace(k, SYMBOLS[k])
    t = re.sub(r"_(\{([^{}]*)\}|(\w))", lambda m: _script(m, SUB), t)
    t = re.sub(r"\^(\{([^{}]*)\}|(\w))", lambda m: _script(m, SUP), t)
    t = re.sub(r"\\[A-Za-z]+", "", t).replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", t).strip()
