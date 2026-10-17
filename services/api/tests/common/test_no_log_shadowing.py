"""A local variable named `log` hides the module logger and crashes only when that line runs (it did: edit_loop, 'list' has no attribute 'info')."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "ai_teacher_api"


def test_no_function_assigns_log():
    bad = []
    for f in SRC.rglob("*.py"):
        for fn in ast.walk(ast.parse(f.read_text())):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Name) and n.id == "log" and isinstance(n.ctx, ast.Store):
                        bad.append(f"{f.name}:{n.lineno}")
    assert not bad, bad
