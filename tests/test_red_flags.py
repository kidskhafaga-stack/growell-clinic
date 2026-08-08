"""The child in the waiting room who should not still be in the waiting room.

The nurse records a temperature and it goes into the file. That is where it
stayed. A two-month-old at 38.2 with vomiting sat in the queue behind eight
routine follow-ups because the number that made him urgent was written down and
read by nobody until his turn came round.

**Why the thresholds are banded by age, and why that is the whole feature.**
One number cannot do this job. 38.0 in a six-week-old is a reason to admit and
investigate; 39.0 in a four-year-old is very often a cold. A single threshold
set high enough not to cry wolf over toddlers is a threshold that silently
ignores the infants who need it most — which is precisely the failure this was
written to prevent. Half the tests below exist to stop somebody "simplifying"
it back to one number.

**It advises; it never triages.** Nothing here reorders the clinic's queue or
refers anybody. It flags, it says why, and a person decides. Software that
silently reorders a waiting room is software nobody trusts the second time it
is wrong.
"""
import os
import sys
from datetime import date, time, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _vitals(**fields):
    base = {"temperature_c": None, "spo2": None, "pulse_bpm": None,
            "resp_rate": None}
    base.update(fields)
    return SimpleNamespace(**base)


def _aged(clinic, months):
    from app.models import Patient

    db = clinic["db"]
    patient = db.session.get(Patient, clinic["ids"]["child"])
    patient.date_of_birth = date.today() - timedelta(days=int(months * 30.44))
    db.session.commit()
    return patient


# ============================================== the age bands ===============
def test_the_same_temperature_means_different_things_at_different_ages(clinic):
    """The reason this is not one number, in one assertion.

    38.2 is an emergency in a six-week-old and unremarkable in a four-year-old.
    A single threshold cannot be right for both, and the one that would not
    annoy anybody about toddlers is the one that misses newborns.
    """
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        infant = assess(_aged(clinic, 1.5), _vitals(temperature_c=38.2))
        assert infant["level"] == "urgent"

        child = assess(_aged(clinic, 48), _vitals(temperature_c=38.2))
        assert child["level"] is None, (
            "38.2 in a four-year-old is not an alert; crying wolf here is how "
            "the infant alert gets ignored")


def test_an_infant_with_any_fever_is_urgent_and_says_why(clinic):
    """A badge reading only "urgent" makes a nurse re-read every number to
    find out why — which is the work this was meant to save. And this rule in
    particular is invisible: 38.0 looks unremarkable to anybody who does not
    already know it."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        result = assess(_aged(clinic, 2), _vitals(temperature_c=38.1))
        assert result["level"] == "urgent"
        assert "infant_fever" in result["reasons"]


def test_a_high_fever_in_an_older_child_is_still_caught(clinic):
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        assert assess(_aged(clinic, 48),
                      _vitals(temperature_c=39.6))["level"] == "urgent"


def test_the_bands_can_be_tuned_per_band_and_not_flattened(clinic):
    """Editable, because a threshold nobody agrees with gets ignored — but
    *per band*, so lowering the tolerance for toddlers can never quietly raise
    it for newborns."""
    from app.models import Setting
    from app.utils.red_flags import assess, bands

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("triage_urgent_3", "39.9")     # the oldest band only
        db.session.commit()

        table = bands()
        assert table[-1][2] == 39.9
        assert table[0][2] == 38.0, "the infant band moved with the older one"
        assert assess(_aged(clinic, 2), _vitals(temperature_c=38.1))["level"] == "urgent"


# ============================================== the pairs the clinic named ==
def test_fever_with_diarrhoea_and_vomiting_is_urgent(clinic):
    """Named in exactly those words: the dehydration pair."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        result = assess(_aged(clinic, 24), _vitals(temperature_c=38.7),
                        "إسهال وترجيع من امبارح")
        assert result["level"] == "urgent"
        assert "fever_gastro" in result["reasons"]


def test_fever_with_only_one_of_them_is_a_lesser_flag(clinic):
    """Diarrhoea alone with a fever is common and is not the same event. A
    system that shouts equally at both is one nobody reads."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        result = assess(_aged(clinic, 24), _vitals(temperature_c=38.7), "اسهال")
        assert result["level"] == "watch"


def test_arabic_is_matched_however_it_was_typed(clinic):
    """"إسهال" and "اسهال" are the same word to everybody except a computer,
    and a nurse types whichever her keyboard gives her."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        for spelling in ("إسهال وترجيع", "اسهال وترجيع", "إسهال و قيء"):
            result = assess(_aged(clinic, 24), _vitals(temperature_c=38.7),
                            spelling)
            assert result["level"] == "urgent", spelling


def test_low_oxygen_outranks_any_temperature(clinic):
    """A comfortable-looking child at 90% is the one a busy room walks past,
    and no thermometer is going to catch them."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        result = assess(_aged(clinic, 60), _vitals(spo2=90))
        assert result["level"] == "urgent"
        assert "spo2_low" in result["reasons"]


def test_a_convulsion_needs_no_fever(clinic):
    """Some things do not wait for a thermometer."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        result = assess(_aged(clinic, 36), _vitals(), "حصله تشنج امبارح")
        assert result["level"] == "urgent"


def test_an_ordinary_cold_raises_nothing(clinic):
    """Guarding the guard. A flag on every child is no flag at all, and the
    second week of that is when the real one gets scrolled past."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        assert assess(_aged(clinic, 36), _vitals(temperature_c=37.2),
                      "كحة ورشح")["level"] is None


def test_a_child_with_no_recorded_vitals_is_not_flagged(clinic):
    """Nothing measured is not the same as nothing wrong, but inventing an
    alert from an empty form would put a flag on the whole waiting room."""
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        assert assess(_aged(clinic, 24), None, "")["level"] is None


def test_an_unknown_age_gets_the_mildest_band(clinic):
    """No date of birth is not a reason to apply an infant's threshold to a
    ten-year-old — nor a ten-year-old's to an infant. It should not be
    answered with a guess in either direction.

    A *stored* patient cannot reach this state: ``date_of_birth`` is NOT NULL,
    and the first version of this test proved that by failing to save one. It
    is still reachable — the assessor is handed whatever object a caller has,
    including a half-built one — and a crash on a screen full of waiting
    children is a worse outcome than a cautious answer.
    """
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        nameless = SimpleNamespace(date_of_birth=None, age_parts=(0, 0))
        result = assess(nameless, _vitals(temperature_c=38.2))
        assert result["level"] is None
        assert result["age_months"] is None


# ============================================== on the nurse's screen =======
def _waiting(clinic, patient, at, **vitals):
    from app.models import Appointment, Visit, VitalSigns

    db = clinic["db"]
    appt = Appointment(patient_id=patient.id, doctor_id=clinic["ids"]["doctor"],
                       appt_date=date.today(), appt_time=at,
                       duration_minutes=15, status="waiting")
    db.session.add(appt)
    db.session.flush()
    visit = Visit(patient_id=patient.id, doctor_id=clinic["ids"]["doctor"],
                  appointment_id=appt.id)
    db.session.add(visit)
    db.session.flush()
    if vitals:
        db.session.add(VitalSigns(visit_id=visit.id, **vitals))
    db.session.commit()
    return appt


def test_the_flag_and_its_reason_reach_the_station(clinic):
    from app.i18n import t

    with clinic["app"].app_context():
        infant = _aged(clinic, 2)
        _waiting(clinic, infant, time(9, 0), temperature_c=38.3)

    page = clinic["sign_in"]("doc").get("/visits/station").data.decode()
    with clinic["app"].test_request_context():
        assert t("redflags.level_urgent") in page
        assert t("redflags.infant_fever") in page


def test_the_urgent_child_is_listed_before_the_well_one(clinic):
    """A nurse's worklist, ordered by who needs attention — not the clinic's
    queue, which nothing here touches."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        infant = _aged(clinic, 2)
        infant.full_name = "رضيع صغير"
        well = Patient(patient_number="P9", full_name="طفل كبير", gender="male",
                       date_of_birth=date.today() - timedelta(days=1500),
                       is_active=True)
        db.session.add(well)
        db.session.commit()
        # The well child was booked *earlier*, so time order alone would put
        # him first.
        _waiting(clinic, well, time(8, 0), temperature_c=37.0)
        _waiting(clinic, infant, time(9, 0), temperature_c=38.3)

    page = clinic["sign_in"]("doc").get("/visits/station").data.decode()
    assert page.index("رضيع صغير") < page.index("طفل كبير")


def test_the_nurse_can_find_one_child_without_scrolling_a_morning(clinic):
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        first = _aged(clinic, 24)
        first.full_name = "زياد محمود"
        other = Patient(patient_number="P8", full_name="مريم سامي",
                        gender="female",
                        date_of_birth=date.today() - timedelta(days=900),
                        is_active=True)
        db.session.add(other)
        db.session.commit()
        _waiting(clinic, first, time(9, 0))
        _waiting(clinic, other, time(9, 30))

    page = clinic["sign_in"]("doc").get("/visits/station?q=زياد").data.decode()
    assert "زياد محمود" in page and "مريم سامي" not in page


def test_the_nurse_can_complete_the_visit_reason(clinic):
    """The nurse hears the fuller story at the scale, and the red-flag read
    depends on those words — "إسهال وترجيع" is what turns a fever into the
    pair the clinic named."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _aged(clinic, 24)
        appt = _waiting(clinic, patient, time(9, 0))
        appt_id = appt.id

    clinic["sign_in"]("doc").post(
        f"/visits/station/{appt_id}/vitals",
        data={"temperature_c": "38.8", "reason": "إسهال وترجيع من امبارح"},
        follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).reason == "إسهال وترجيع من امبارح"

    page = clinic["sign_in"]("doc").get("/visits/station").data.decode()
    from app.i18n import t
    with clinic["app"].test_request_context():
        assert t("redflags.fever_gastro") in page, (
            "the reason the nurse typed did not reach the red-flag read")


def test_nothing_here_reorders_the_clinics_queue(clinic):
    """The station sorts its own worklist. The appointment board is the
    clinic's queue and this must not touch it — software that silently
    reorders a waiting room is not trusted the second time it is wrong."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        infant = _aged(clinic, 2)
        appt = _waiting(clinic, infant, time(9, 0), temperature_c=38.3)
        before = (appt.appt_time, appt.status)

    clinic["sign_in"]("doc").get("/visits/station")

    with clinic["app"].app_context():
        appt = Appointment.query.one()
        assert (appt.appt_time, appt.status) == before


# ============================================== and on the doctor's screen ==
def test_the_doctor_sees_it_on_their_own_list(clinic):
    """The half the nurse cannot do.

    A nurse records 38.4 in a six-week-old; whether that is serious is a
    judgement, and the doctor is the one who makes it. Until now it was only
    on the station screen the doctor never opens, so the flag had to travel to
    the list they are actually looking at.
    """
    from app.i18n import t

    with clinic["app"].app_context():
        infant = _aged(clinic, 1.5)
        _waiting(clinic, infant, time(9, 0), temperature_c=38.4)

    page = clinic["sign_in"]("doc").get("/appointments/").data.decode()
    with clinic["app"].test_request_context():
        assert "rf-urgent" in page
        assert t("redflags.infant_fever") in page, (
            "the flag arrived without its reason, which is the part that makes "
            "it act-on-able")


def test_reception_sees_it_across_the_whole_clinic(clinic):
    """Reception watches every عيادة and is who can go and knock on a door."""
    from app.i18n import t

    with clinic["app"].app_context():
        infant = _aged(clinic, 1.5)
        _waiting(clinic, infant, time(9, 0), temperature_c=38.4)

    page = clinic["sign_in"]("boss").get("/appointments/").data.decode()
    with clinic["app"].test_request_context():
        assert t("redflags.in_queue") in page


def test_a_finished_visit_stops_flagging(clinic):
    """History on a live board is noise, and noise is what teaches people to
    stop reading the colour. Only the ones still waiting or in the room."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        infant = _aged(clinic, 1.5)
        appt = _waiting(clinic, infant, time(9, 0), temperature_c=38.4)
        appt.status = "completed"
        db.session.commit()

    page = clinic["sign_in"]("doc").get("/appointments/").data.decode()
    assert "rf-urgent" not in page


def test_a_board_of_well_children_carries_no_colour_at_all(clinic):
    """Guarding the guard, on the screen where it matters most: a board where
    every row is flagged is a board where none of them is."""
    with clinic["app"].app_context():
        child = _aged(clinic, 36)
        _waiting(clinic, child, time(9, 0), temperature_c=37.1)

    page = clinic["sign_in"]("doc").get("/appointments/").data.decode()
    assert "rf-urgent" not in page and "rf-watch" not in page
