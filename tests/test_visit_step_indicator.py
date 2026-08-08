"""The highlight that slides from one step to the next.

*"عايز الطبيب يحس ان الموضوع متسلسل"* — the visit screen is eight numbered
steps, and until now the current one was marked by a colour that simply
appeared somewhere else on the strip when you pressed a button. A highlight
that *travels* is what makes eight buttons read as a sequence rather than
eight unrelated tabs: the doctor sees the direction they moved in.

Everything below is a source invariant rather than a rendered pixel: the
motion happens in a browser and this suite has none. What can be pinned is
the part that would break silently — the fallback when the script does not
run, and the promise this program makes everywhere else about movement.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RECORD = os.path.join(os.path.dirname(__file__), "..", "app", "templates",
                      "visits", "record.html")


def _source():
    with open(RECORD, encoding="utf-8") as fh:
        return fh.read()


def test_the_strip_carries_the_moving_highlight(clinic):
    """It reaches the browser at all."""
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").data.decode()
    assert "vtab-pill" in page
    assert "movePill" in page


def test_the_highlight_is_placed_after_the_class_moves(clinic):
    """Measuring the active button before Alpine has moved the ``active``
    class puts the highlight on the step the doctor just left, and it stays
    one behind for the rest of the consultation."""
    source = _source()
    assert "$nextTick(() => this.movePill())" in source


def test_a_browser_that_runs_no_script_still_shows_the_current_step(clinic):
    """The plain colour is the fallback, and it is only given up once the
    highlight has actually been positioned. A step strip with nothing marked
    is worse than one that does not animate."""
    source = _source()
    # The active button keeps its own colour…
    assert ".vtab.active { background:var(--green-600);" in source
    # …and only hands it over under the class the script adds.
    assert ".visit-tabs.has-pill .vtab.active { background:transparent;" in source
    assert "strip.classList.add('has-pill')" in source


def test_the_highlight_is_hidden_until_it_knows_where_to_go(clinic):
    """Otherwise it appears at the corner of the strip on first paint and
    flies across, which reads as a glitch rather than as a position."""
    source = _source()
    assert "opacity:0" in source.split(".vtab-pill {")[1].split("}")[0]
    assert ".visit-tabs.has-pill .vtab-pill { opacity:1; }" in source


def test_it_is_repositioned_when_the_window_changes(clinic):
    """The strip wraps onto two lines on a narrow screen, so every button
    moves. A highlight measured once is in the wrong place afterwards."""
    assert "resize.window" in _source()


def test_somebody_who_asked_for_less_movement_gets_less(clinic):
    """Every other animation in this program honours it, and a bouncing
    highlight is exactly what the setting is for."""
    source = _source()
    block = source.split("@media (prefers-reduced-motion: reduce)")[1]
    assert ".vtab-pill" in block.split("}")[0] or "vtab-pill" in block[:200]


def test_the_highlight_is_not_read_aloud(clinic):
    """It is a decoration over a button that already says what it is. A
    screen reader announcing an empty element between the steps is noise."""
    source = _source()
    pill = source.split('x-ref="tabpill"')[0].rsplit("<span", 1)[-1] + \
        source.split('x-ref="tabpill"')[1].split(">")[0]
    assert 'aria-hidden="true"' in pill
