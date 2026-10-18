import json

from ai_teacher_api.content import run_plan


def chapter(n_pages: int, chars: int) -> dict:
    return {"book": "b", "title": "t", "activities": [], "pages": [{"page": i + 1, "text": "क" * chars} for i in range(n_pages)]}


def test_pages_that_fit_cuts_a_whole_book_to_its_first_pages():
    assert run_plan.pages_that_fit(chapter(10, 1000), 1_000_000) == 10
    assert run_plan.pages_that_fit(chapter(300, 10_000), 1_000_000) == 99
    assert run_plan.chapter_prompt(chapter(5, 10), "hi-IN", "Bihar", 6, 2).count("=== PAGE") == 2


def test_too_long_error_retries_with_fewer_pages(tmp_path, monkeypatch):
    f = tmp_path / "chapter.json"
    f.write_text(json.dumps(chapter(40, 100)))
    seen = []

    async def fake(ch, *, model, language, region, grade, pages_limit=None):
        seen.append(pages_limit)
        if pages_limit > 10:
            raise RuntimeError("400 INVALID_ARGUMENT: The input token count exceeds the maximum number of tokens allowed")
        from ai_teacher_api.content.plan import LessonPlan
        return LessonPlan(chapter="t", language="hi-IN", region="Bihar", lessons=[])

    monkeypatch.setattr(run_plan, "plan_chapter", fake)
    r = run_plan.run(f, tmp_path / "plan.json", "gemini-3.6-flash")
    assert seen == [40, 20, 10] and r == {"pages_used": 10, "pages_total": 40}
