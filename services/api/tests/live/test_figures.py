from ai_teacher_api.live import figures, prepare


GOOD = '<div class="fig"><style>.fig{display:flex}</style><p>घर्षण बल →</p></div>'


def test_good_figure_passes():
    assert figures.check_html(GOOD) == []


def test_bad_figures_are_rejected():
    assert figures.check_html('<p>घर्षण</p>')  # must start with the fig div
    assert figures.check_html('<div class="fig"><script>alert(1)</script>घर्षण</div>')
    assert figures.check_html('<div class="fig"><img src="x.png">घर्षण</div>')
    assert figures.check_html('<div class="fig" onclick="x()">घर्षण</div>')
    assert figures.check_html('<div class="fig"><style>.a{background:url(http://x/y)}</style>घर्षण</div>')
    assert figures.check_html('<div class="fig"><style>@import "x.css";</style>घर्षण</div>')
    assert figures.check_html('<div class="fig"><style>.a{position:fixed}</style>घर्षण</div>')
    assert figures.check_html('<div class="fig">only english</div>')  # no Hindi text
    assert figures.check_html('<div class="fig">' + "घ" * 8000 + "</div>")  # too long


def _spec(name, step):
    return prepare.PicSpec(name=name, step=step, intent="i", description="d", caption="c")


def test_kit_counts_and_coverage_are_checked():
    steps = ["a", "b", "c"]
    pics = [_spec(f"p{i}", steps[i % 3]) for i in range(4)]
    figs = [_spec(f"f{i}", steps[i % 3]) for i in range(7)]
    assert prepare.kit_problems(prepare.KitPlan(steps=steps, pictures=pics, figures=figs)) == []
    assert any("figures" in p for p in prepare.kit_problems(prepare.KitPlan(steps=steps, pictures=pics, figures=figs[:3])))
    assert any("without any" in p for p in prepare.kit_problems(prepare.KitPlan(steps=steps + ["d"], pictures=pics, figures=figs)))
