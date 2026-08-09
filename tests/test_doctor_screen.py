"""What the doctor sees before they start typing.

Two faults on the visit recording screen, both found by opening it rather than
by reading it.

**The current step was the one step nobody could see.** The eight-tab strip
draws its highlight as a separate element that slides to whichever tab is
active, and the active tab gives up its own background so two blues do not
chase each other. The sliding element was positioned by ``transform`` alone,
with no ``left``/``top`` — so it kept its *static* position, which in a
right-to-left row is the right-hand end of the strip, already level with the
first tab. Translating by the tab's offset then moved it that distance again
and it landed 440px past the edge of a 1400px window. Left-to-right never
showed it: there the static position is the strip's origin, so the translate
happened to be right. The clinic works in Arabic, where the result was white
text on a white page over the step the doctor was on.

**The age band stayed at the nurse's station.** ``red_flags.assess_visit`` was
written and then called from nowhere; the flag reached the station and the
appointments board and stopped there. The doctor's screen showed a red-tinted
temperature box, which says "this number is high" — but not "this number is
high *for a child this age*", and the band is the entire content of the rule.
38.6 is a cold in a four-year-old and a workup in a six-week-old, and the
screen that has to tell those apart was the one screen not saying so.
"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RECORD = os.path.join(os.path.dirname(__file__), "..",
                      "app", "templates", "visits", "record.html")


def _rule(css, selector):
    """The declarations of one CSS rule, as written in the template."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else ""


def test_the_sliding_highlight_is_anchored_to_the_strip():
    """``transform`` moves a box from wherever it already is.

    The script measures ``offsetLeft`` — a distance from the strip's own corner
    — and hands it to ``translate``. That arithmetic is only true if the box
    starts at that corner, which takes an explicit ``left``/``top``. Without
    them the browser leaves it at its static position, and in Arabic that is
    the far end of the row, so the highlight lands a screen-width away and the
    active tab (which has given up its background) renders white on white.
    """
    css = open(RECORD, encoding="utf-8").read()
    pill = _rule(css, ".vtab-pill")
    assert "position:absolute" in pill.replace(" ", "")
    body = pill.replace(" ", "")
    assert "left:0" in body, ".vtab-pill must be anchored to the strip's corner"
    assert "top:0" in body, ".vtab-pill must be anchored to the strip's corner"


def test_the_active_tab_relies_on_the_highlight_for_its_colour():
    """Why the anchoring above is not cosmetic.

    Once the highlight is placed, the active button is deliberately stripped of
    its own background and left with white text. That is a sound trade *only*
    while the highlight is behind it. This test records the coupling, so that
    anybody who removes the anchor is removing the readability of the step the
    doctor is standing on, not a decoration.
    """
    css = open(RECORD, encoding="utf-8").read()
    active = _rule(css, ".visit-tabs.has-pill .vtab.active").replace(" ", "")
    assert "background:transparent" in active
    assert "color:#fff" in _rule(css, ".vtab.active").replace(" ", "")


def _vitals(clinic, **kw):
    """Put vitals on the fixture's open visit and hand back the visit id."""
    with clinic["app"].app_context():
        from app.models import VitalSigns
        row = VitalSigns(visit_id=clinic["ids"]["visit"], **kw)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
    return clinic["ids"]["visit"]


def test_the_doctor_is_told_which_child_should_not_be_waiting(clinic):
    """The judgement the station makes, in front of the person who decides."""
    visit = _vitals(clinic, temperature_c=38.7)
    page = clinic["sign_in"]("doc").get(f"/visits/{visit}/record")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "محتاجة نظرة" in body
    assert "حرارة" in body


def test_the_screen_states_the_limit_it_judged_against(clinic):
    """A colour is not an argument; a number a doctor can disagree with is.

    The banner prints the band it used, so a doctor who thinks 38.5 is the
    wrong line for a toddler can see the line rather than the verdict — and
    knows there is a setting behind it.
    """
    visit = _vitals(clinic, temperature_c=38.7)
    body = clinic["sign_in"]("doc").get(f"/visits/{visit}/record").get_data(as_text=True)
    assert "38.5" in body and "39.0" in body


def test_a_well_child_gets_no_banner(clinic):
    """A warning that is always there is furniture.

    The fixture's child at 37.0 with nothing else wrong must produce no flag at
    all — otherwise the doctor learns to scroll past the strip that matters.
    """
    visit = _vitals(clinic, temperature_c=37.0, spo2=99)
    body = clinic["sign_in"]("doc").get(f"/visits/{visit}/record").get_data(as_text=True)
    assert "محتاجة نظرة" not in body
    assert "حالة تستاهل تتشاف دلوقتي" not in body


def test_the_same_temperature_reads_differently_by_age(clinic):
    """The whole reason this belongs on the doctor's screen.

    38.2 in the fixture's toddler is nothing. The same 38.2 in a six-week-old
    is urgent.

    What this pins, specifically, is the standalone under-three-months rule
    rather than the band table — deliberately, and the difference was measured:
    flattening all four bands to the toddler's numbers leaves this test green,
    because that rule fires on its own. Two guards, and this is the test for
    the second one. It is the one worth a test of its own, since any flat
    threshold would be chosen high enough not to cry wolf over toddlers and
    would therefore be silent about exactly the babies the rule exists for.
    """
    from datetime import timedelta

    with clinic["app"].app_context():
        from app.models import Patient, Visit, VitalSigns
        db = clinic["db"]
        baby = Patient(patient_number="P-BABY", full_name="رضيع",
                       gender="female",
                       date_of_birth=date.today() - timedelta(days=42),
                       is_active=True)
        db.session.add(baby)
        db.session.flush()
        baby_visit = Visit(patient_id=baby.id,
                           doctor_id=clinic["ids"]["doctor"],
                           visit_date=date.today())
        db.session.add(baby_visit)
        db.session.flush()
        db.session.add(VitalSigns(visit_id=baby_visit.id, temperature_c=38.2))
        db.session.commit()
        baby_visit_id = baby_visit.id

    toddler = _vitals(clinic, temperature_c=38.2)
    client = clinic["sign_in"]("doc")
    toddler_page = client.get(f"/visits/{toddler}/record").get_data(as_text=True)
    baby_page = client.get(f"/visits/{baby_visit_id}/record").get_data(as_text=True)

    assert "محتاجة نظرة" not in toddler_page
    assert "حالة تستاهل تتشاف دلوقتي" in baby_page
    assert "رضيع أقل من ٣ شهور بحرارة" in baby_page


def test_the_flag_is_not_printed_with_the_visit(clinic):
    """It is a prompt for the room, not a line in the record.

    What the doctor concluded belongs in the notes they wrote. A machine's
    "worth a look" printed on a patient's paper reads like a diagnosis nobody
    made, so the banner carries ``no-print``.
    """
    visit = _vitals(clinic, temperature_c=38.7)
    body = clinic["sign_in"]("doc").get(f"/visits/{visit}/record").get_data(as_text=True)
    where = body.index("محتاجة نظرة")
    assert "no-print" in body[max(0, where - 400):where]


def test_low_oxygen_outranks_a_normal_temperature(clinic):
    """The comfortable-looking child at 90% is the one a busy room walks past.

    Carried onto the doctor's screen deliberately: the temperature box is the
    one that turns red, so a child whose only abnormal number is saturation
    would otherwise arrive at this screen looking entirely unremarkable.
    """
    visit = _vitals(clinic, temperature_c=36.9, spo2=90)
    body = clinic["sign_in"]("doc").get(f"/visits/{visit}/record").get_data(as_text=True)
    assert "حالة تستاهل تتشاف دلوقتي" in body
    assert "الأكسجين منخفض" in body
