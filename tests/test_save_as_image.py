"""Saving a prescription as an image — the button that never once worked.

A "save as image" button shipped in this program and produced nothing, ever.
It rasterised the page through an SVG ``<foreignObject>``, which **taints the
canvas** in Chromium — every clinic — so ``toDataURL`` threw ``SecurityError``
and the handler fell through to ``window.print()``. It looked like a print
button with the wrong label, and nobody could say why. It was removed, with a
comment saying the approach is impossible, which it is.

html2canvas takes the other route: it walks the DOM and repaints it onto the
canvas itself, never touching SVG, so nothing taints. It is vendored into
``app/static/vendor`` rather than loaded from a CDN, because a clinic with no
internet still has to be able to send a prescription.

**Three things had to be fixed before a single readable pixel came out**, and
none of them were guessable — each was found by rendering, measuring the
result, and looking at what the numbers said:

1. ``color-mix(in srgb, …)`` — how one ``--accent`` recolours the whole brand
   — computes to ``color(srgb …)``, a syntax the library's 2022 parser rejects
   by throwing. Every capture failed.
2. Every card in this program enters with ``gc-scale-in``, whose first
   keyframe is ``opacity: 0``. The renderer works on a *clone*, and a cloned
   element restarts its animations — so the first successful render was a
   correct prescription with **no pixel darker than (228,230,231)**.
3. With a non-zero ``letter-spacing`` the library positions each character
   itself, and Arabic is contextual: its letters stopped joining. "المريض"
   came out "لم ي ض" and "الجرعة" came out "لج رعة" — on exactly the labels
   and table headers where the theme adds 0.4px of tracking, and nowhere else.

The tests below pin all three, because each one produced a file that looked
plausible until it was measured.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_JS = os.path.join(ROOT, "app", "static", "js", "app.js")
VENDOR = os.path.join(ROOT, "app", "static", "vendor")


def _onclone(js):
    """The body of the `onclone` callback, which is where the fixes must run.

    Asserting a function merely *exists* is what let three mutations through:
    deleting each call from `onclone` left every test green while the renderer
    silently went back to producing washed-out, mis-shaped output. A function
    defined and never called is a bug this program has already shipped once.
    """
    start = js.index("onclone:")
    return js[start:start + 400]


def _js():
    return open(APP_JS, encoding="utf-8").read()


def test_the_library_is_ours_not_a_cdns():
    """A clinic with no internet still has to be able to send a prescription.

    Every other dependency in this program is vendored for the same reason;
    a script tag pointing at a CDN would work in testing and fail in the room
    where it matters.
    """
    assert os.path.exists(os.path.join(VENDOR, "html2canvas.min.js"))
    # MIT, and the licence travels with the file rather than being assumed.
    assert os.path.exists(os.path.join(VENDOR, "html2canvas.LICENSE.txt"))
    js = _js()
    assert "/static/vendor/html2canvas.min.js" in js
    assert "cdn" not in js.lower().split("html2canvas")[0][-200:]


def test_the_renderer_is_not_the_one_that_cannot_work():
    """The old approach must not come back.

    Rasterising through ``<foreignObject>`` taints the canvas in Chromium and
    can never produce a file. It shipped once and silently printed instead;
    the reason it is impossible is written down beside the working code so the
    next person does not spend an afternoon rediscovering it.
    """
    live = re.sub(r"^\s*//.*$", "", _js(), flags=re.M)        # strip comments
    # The word may appear in the comment explaining why it cannot work; it
    # must not appear in anything that runs.
    assert "foreignObject" not in live
    assert "html2canvas" in live


def test_animations_are_settled_before_the_page_is_drawn():
    """Otherwise the capture is of a page mid-entrance — which is invisible.

    The first working render produced a correct prescription in which no pixel
    was darker than (228,230,231): right layout, right text, all of it at
    nearly zero opacity, because ``gc-scale-in`` starts at ``opacity: 0`` and
    restarts in the clone.

    Zero duration with the ``both`` fill mode the animations already declare
    lands each one on its *last* keyframe — which settles whatever it animates
    rather than naming opacity and being wrong about the next animation
    somebody adds.
    """
    js = _js()
    assert "animation-duration: 0s !important" in js
    assert "animation-delay: 0s !important" in js
    assert "settleAnimations(doc)" in _onclone(js)


def test_arabic_is_not_drawn_one_letter_at_a_time():
    """The defect that would have made the whole feature useless here.

    A prescription image whose field labels read "لم ي ض" is not something a
    pharmacy accepts. Only elements actually containing Arabic are touched, so
    the Latin wordmark keeps its tracking — losing 0.4px on a label is
    invisible, losing the shaping is not.
    """
    js = _js()
    assert "unspaceArabic(doc)" in _onclone(js)
    assert "letter-spacing" in js
    # The Arabic ranges, including the presentation forms.
    assert "u0600-" in js and "u06FF" in js


def test_modern_colours_are_rewritten_for_a_2022_parser():
    """``color-mix`` is how one ``--accent`` recolours the brand.

    Chromium computes it to ``color(srgb …)``, which the library rejects by
    throwing rather than skipping — so every capture failed until this. The
    conversion is exact: the same numbers in 0–1 that rgb() carries in 0–255.
    """
    js = _js()
    assert "flattenColours(doc)" in _onclone(js)
    # It must match Chromium's actual serialisation — the literal
    # ``color(srgb``, escaped for the regex — not merely mention srgb.
    assert r"color\(srgb" in js
    # 255, because that is the whole of the arithmetic: the same numbers in
    # 0–1 that rgb() carries in 0–255.
    assert "* 255" in js


def test_every_computed_property_is_swept_not_a_chosen_list():
    """Because the chosen list was tried first and was wrong.

    ``color(srgb …)`` turned up in 80 declarations on one prescription page,
    including logical properties (``border-inline-start-color``) and inside
    gradient stacks. Enumerating which properties can hold a colour is a
    losing game; CSS keeps adding them.
    """
    js = _js()
    # The sweep reads the computed style's own index rather than a literal
    # list of property names.
    assert "computed.length" in js
    assert "COLOUR_PROPS" not in js


def test_the_furniture_is_left_out_of_the_document():
    """Buttons and navigation have no business in a saved copy.

    ``.no-print`` already marks them for the printer; the same mark serves
    here, so one class governs both and they cannot drift apart.
    """
    js = _js()
    assert "ignoreElements" in js
    assert "no-print" in js


def test_a_failure_still_leaves_the_user_somewhere():
    """Never a dead button.

    If the library will not load, printing is the route that always works —
    and is where a PDF comes from anyway. The difference from the old
    behaviour is that printing is now the *fallback*, not the silent result.
    """
    js = _js()
    handler = js[js.index("gcSaveImage"):]
    assert "window.print()" in handler
    assert "finally" in handler          # the button is always re-enabled


def test_the_prescription_offers_it(clinic):
    """On the copy that goes to the family, where a file is what is wanted."""
    with clinic["app"].app_context():
        from datetime import date

        from app.models import Prescription, RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="أبيض", mode="white",
                                       page_size="A4", is_default=True))
        rx = Prescription(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          rx_date=date.today())
        db.session.add(rx)
        db.session.commit()
        rx_id = rx.id

    body = (clinic["sign_in"]("doc").get(f"/prescriptions/{rx_id}?digital=1")
            .get_data(as_text=True))
    assert "gcSaveImage('#rxPaper'" in body


def test_the_reports_offer_it_too(clinic):
    """"Everywhere" meant everywhere, and `.print-area` is what makes it cheap.

    The convention already existed for the printer — the part of the page that
    is the document, as opposed to the toolbar around it — so the image and
    the printout are defined by one marker and cannot disagree about what the
    document is.
    """
    body = (clinic["sign_in"]("boss").get("/reports/financial")
            .get_data(as_text=True))
    assert "gcSaveImage('.print-area'" in body
    assert "print-area" in body
