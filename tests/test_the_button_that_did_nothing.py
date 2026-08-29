"""Three screens that accepted a press and did nothing with it.

Reported together, from a clinic actually using the program.

**Cancelling an appointment answered "The CSRF token is missing".** The board
posts by building a ``<form>`` in script and submitting it — a navigation, not
a ``fetch`` — so the wrapper in ``base.html`` that attaches the token to every
scripted ``fetch`` never saw it. Five actions went through that helper and all
five were dead: cancel, no-show, reschedule, walk-in and the waitlist. A sixth
copy of the same trick, in the prescription writer, meant *save preset* had
never once worked either. One shared helper now, so the next screen that posts
this way cannot forget.

**Checkout confirmed and collected nothing.** Every charge a visit would raise
is skipped once it is already on today's invoice — so a patient billed earlier
today opened a checkout with no lines, a total of zero, and a confirm button
that wrote nothing and took no money. Reported as *"بحصّل خلاص مش بتسمع مع إن
كل الإجراءات صح"*. The skipping is right; the silence was not.

**And the prescription printed a doctor with no title.** The rule that turns
"أحمد" into "د/ أحمد" was there and correct, and one field switched it off:
``rx_display_name`` was returned untouched, so a doctor who filled in the
prescription-name box — which is what the box asks for — lost their title
everywhere they printed.
"""
import os
import re
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ------------------------------------------- a form built in script has a token

def _script_forms():
    """Every place a template builds a form element in JavaScript."""
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    hits = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith((".html", ".js")):
                continue
            path = os.path.join(base, name)
            text = open(path, encoding="utf-8").read()
            if re.search(r"createElement\(['\"]form['\"]\)", text):
                hits.append((path, text))
    return hits


def test_no_screen_builds_its_own_form_any_more():
    """The rule, where it can actually be enforced. A form built by hand is a
    form somebody has to remember to put a token on, and the two that existed
    both forgot."""
    for path, text in _script_forms():
        assert "csrf" in text.lower(), (
            f"{os.path.relpath(path)} builds a form in script without a token — "
            "use window.gcPostForm")


def _helper_source():
    """The `gcPostForm` function, lifted out of base.html."""
    base = open(os.path.join(os.path.dirname(__file__), "..", "app",
                             "templates", "base.html"), encoding="utf-8").read()
    assert "window.gcPostForm" in base, "the shared helper is gone"
    start = base.index("window.gcPostForm")
    end = base.index("form.submit();", start) + len("form.submit();")
    return base[start:end] + "\n};"


def test_the_shared_helper_sends_the_token(tmp_path):
    """**Run, not read.** Grepping the helper for the word `csrf_token` passes
    against `if (false) add('csrf_token', …)` — the string is still there and
    the token still never goes. So the function is lifted out and executed
    against a stub DOM, and the assertion is on what it actually built.

    This is the only way to test it without a browser, and the bug it guards
    is precisely a piece of JavaScript that looked right in the source."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:                       # pragma: no cover - CI has node
        pytest.skip("node is not installed")

    script = tmp_path / "run.js"
    script.write_text("""
var submitted = null;
var meta = { content: 'THE-TOKEN' };
var document = {
  querySelector: function (sel) {
    return sel.indexOf('csrf-token') !== -1 ? meta : null;
  },
  createElement: function (tag) {
    return { tagName: tag, children: [], appendChild: function (c) {
      this.children.push(c); }, submit: function () { submitted = this; } };
  },
  body: { appendChild: function () {} }
};
var window = {};
""" + _helper_source() + """
window.gcPostForm('/appointments/9/status', { status: 'cancelled' });
var fields = {};
(submitted.children || []).forEach(function (c) { fields[c.name] = c.value; });
console.log(JSON.stringify({ action: submitted.action, fields: fields }));
""", encoding="utf-8")

    out = subprocess.run([node, str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)

    assert result["fields"].get("csrf_token") == "THE-TOKEN", \
        "the helper submitted a form with no CSRF token on it"
    assert result["fields"].get("status") == "cancelled", \
        "the helper dropped the caller's own fields"
    assert result["action"] == "/appointments/9/status"


def test_cancelling_an_appointment_goes_through_the_helper(clinic):
    """The report itself: pressing cancel produced a 400 page."""
    board = open(os.path.join(os.path.dirname(__file__), "..", "app",
                              "templates", "appointments",
                              "board.html"), encoding="utf-8").read()

    assert "window.gcPostForm" in board
    assert "createElement('form')" not in board, \
        "the board is building its own form again"


def test_the_status_route_accepts_what_the_board_sends(clinic):
    """End to end, because the two halves drifted apart without either one
    being wrong on its own."""
    from app.extensions import db
    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(10, 0),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id

    client = clinic["sign_in"]("boss")
    page = client.get("/appointments/").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    answer = client.post(f"/appointments/{appt_id}/status",
                         data={"status": "cancelled", "cancel_reason": "dd",
                               "csrf_token": token}, follow_redirects=True)

    # A missing token answers 400 and changes nothing, so these two together
    # are the whole claim. Grepping the page for the words is not: the page
    # carries them in its own script and in the comment explaining this bug.
    assert answer.status_code == 200
    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).status == "cancelled"


# ------------------------------------- a checkout with nothing left to charge

@pytest.fixture()
def billed(clinic):
    """A patient whose visit charge is already on today's invoice."""
    from app.extensions import db
    from app.models import Appointment, Invoice, InvoiceItem, Service
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        today = local_today()
        exam = Service.query.filter_by(name="كشف").first()
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=today, appt_time=time(11, 0),
                           appt_type="consultation", status="scheduled")
        db.session.add(appt)
        invoice = Invoice(invoice_number="INV-X1",
                          patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_date=today)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, service_id=exam.id,
                                   description=exam.name, quantity=1,
                                   unit_price=exam.price))
        db.session.commit()
        clinic["appt"] = appt.id
        clinic["invoice_number"] = invoice.invoice_number
    return clinic


def test_it_says_the_visit_is_already_on_an_invoice(billed):
    """Instead of an empty table and a confirm button that does nothing."""
    page = billed["sign_in"]("boss").get(
        f"/finance/checkout/{billed['appt']}").get_data(as_text=True)

    assert "checkout.nothing_left" not in page, \
        "the strings are keys, not translations"
    assert billed["invoice_number"] in page, \
        "the screen does not name the invoice that already carries the visit"


def test_a_visit_with_something_to_charge_says_no_such_thing(billed):
    """The other half, and it needs the harder case to mean anything: a
    patient who *does* have an invoice today **and** still has something
    unbilled. Say it on every checkout that happens to follow an invoice and
    the notice becomes wallpaper — read past, then missed on the day it is
    true."""
    from app.extensions import db
    from app.models import Appointment, Service
    from app.utils.clock import local_today

    with billed["app"].app_context():
        # A second appointment of a different type, whose charge is not on
        # today's invoice — so there is a real line to collect.
        nebul = Service.query.filter_by(name="جلسة تنفس").first()
        appt = Appointment(patient_id=billed["ids"]["child"],
                           doctor_id=billed["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(12, 0),
                           appt_type="consultation", status="scheduled",
                           extra_service_ids=str(nebul.id))
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id

    page = billed["sign_in"]("boss").get(
        f"/finance/checkout/{appt_id}").get_data(as_text=True)

    assert "جلسة تنفس" in page, "the unbilled charge is not proposed at all"
    assert billed["invoice_number"] not in page, \
        "the 'nothing left to charge' notice showed on a checkout that has "\
        "something to charge"


# --------------------------------------------- the title in front of the name

def test_a_doctor_gets_a_title_without_typing_one(clinic):
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "أحمد جمال قنديل"
        doctor.full_name_en = "Ahmed Gamal Kandil"
        db.session.commit()

        assert doctor.doctor_print_name("ar") == "د/ أحمد جمال قنديل"
        assert doctor.doctor_print_name("en") == "Dr. Ahmed Gamal Kandil"


def test_a_professor_is_addressed_as_one(clinic):
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "أحمد جمال قنديل"
        doctor.full_name_en = "Ahmed Gamal Kandil"
        doctor.professional_title = "Professor"
        db.session.commit()

        assert doctor.doctor_print_name("ar").startswith("أ.د/")
        assert doctor.doctor_print_name("en").startswith("Prof. Dr.")


def test_the_prescription_name_field_no_longer_eats_the_title(clinic):
    """The fault. A doctor filled the prescription-name box with their plain
    name — which is what the box asks for — and the title disappeared from
    every prescription they printed."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "أحمد جمال قنديل"
        doctor.full_name_en = "Ahmed Gamal Kandil"
        doctor.rx_display_name = "Ahmed Gamal Kandil"   # their own name
        db.session.commit()

        assert doctor.doctor_print_name("en") == "Dr. Ahmed Gamal Kandil"


def test_a_clinic_name_in_that_field_is_not_addressed_as_a_doctor(clinic):
    """The case the literal rule was protecting, and the reason the two are
    told apart rather than guessed at: some clinics put the *practice* name on
    the paper, and "د/ العيادة التخصصية للأطفال" is nonsense."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "أحمد جمال قنديل"
        doctor.rx_display_name = "العيادة التخصصية للأطفال"
        db.session.commit()

        assert doctor.doctor_print_name("ar") == "العيادة التخصصية للأطفال"


def test_the_same_name_spaced_differently_is_still_the_same_name(clinic):
    """A double space typed into the box must not be the difference between a
    doctor having a title and not having one."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "أحمد جمال قنديل"
        doctor.rx_display_name = "  أحمد  جمال   قنديل "
        db.session.commit()

        assert doctor.doctor_print_name("ar").startswith("د/")


def test_a_title_somebody_typed_themselves_is_left_alone(clinic):
    """No "د/ د/ أحمد". A doctor who writes their own title keeps it exactly."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        for typed in ("د/ أحمد", "د. أحمد", "أ.د/ أحمد", "Dr. Ahmed",
                      "Prof. Dr. Ahmed"):
            doctor.rx_display_name = typed
            assert doctor.doctor_print_name("ar") == typed
            assert doctor.doctor_print_name("en") == typed
