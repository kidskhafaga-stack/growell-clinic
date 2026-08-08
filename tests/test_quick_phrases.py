"""Each doctor's own shorthand, and codes that write whole sentences.

Two requests, one feature seen from two sides.

*"طبيب السكر غير طبيب حديثي الولادة، دكتور القلب غير حد تاني، والغدد"* — one
clinic-wide list of quick phrases is the wrong shape. It grows until finding a
sentence costs more than typing it, and most of what is in it belongs to
somebody else's specialty.

*"ممكن نعمل اختصارات طويلة تبقى باختصار زي نورمال"* — the visit screen already
had a single button that wrote a whole normal-examination paragraph, which is
exactly what a doctor wants for every sentence they repeat. So a phrase can
carry a short **code**: type it, press space, and the sentence arrives.

The storage is the interesting constraint. Clinics already have lists on disk
written as ``ar|en`` lines, and a format change that lost them would be a much
worse bug than the missing feature. So a third field is a third part —
``code|ar|en`` — and a two-part line still means what it always meant.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _phrases():
    from app.utils import phrases

    return phrases


def _set_clinic(clinic, field, text):
    from app.models import Setting
    from app.utils import phrases

    Setting.set(phrases.key_for(field), text)
    clinic["db"].session.commit()


def _set_doctor(clinic, user_id, field, text):
    from app.models import User
    from app.utils import phrases

    db = clinic["db"]
    setattr(db.session.get(User, user_id), phrases.key_for(field), text)
    db.session.commit()


# ============================================== the stored format ===========
def test_a_line_with_a_code_carries_all_three(clinic):
    with clinic["app"].app_context():
        rows = _phrases().parse("نورمال|الفحص طبيعي|Examination normal")
        assert rows == [{"code": "نورمال", "ar": "الفحص طبيعي",
                         "en": "Examination normal"}]


def test_the_lists_clinics_already_have_still_read(clinic):
    """The whole reason the code is a *third* part. Every clinic on disk today
    has two-part lines, and a format that could not read them would lose a
    doctor's list on the day they upgraded."""
    with clinic["app"].app_context():
        rows = _phrases().parse("حرارة|Fever\nكحة")
        assert rows == [{"code": "", "ar": "حرارة", "en": "Fever"},
                        {"code": "", "ar": "كحة", "en": ""}]


def test_a_sentence_may_contain_a_pipe(clinic):
    """A code cannot contain one; a sentence is under no such obligation, and
    splitting on every pipe would quietly truncate somebody's phrase."""
    with clinic["app"].app_context():
        rows = _phrases().parse("hr|القلب سليم|Heart: S1|S2 normal")
        assert rows[0]["en"] == "Heart: S1|S2 normal"


def test_writing_and_reading_come_back_the_same(clinic):
    """Round trip. The screen writes what this module reads, and a mismatch
    would show up as phrases that change shape every time they are saved."""
    with clinic["app"].app_context():
        phrases = _phrases()
        original = [{"code": "نورمال", "ar": "طبيعي", "en": "Normal"},
                    {"code": "", "ar": "كحة", "en": "Cough"},
                    {"code": "", "ar": "مغص", "en": ""}]
        assert phrases.parse(phrases.serialise(original)) == original


def test_an_empty_row_is_not_stored(clinic):
    """The editor always leaves a blank row at the bottom to type into."""
    with clinic["app"].app_context():
        assert _phrases().serialise([{"code": "x", "ar": "", "en": ""}]) == ""


# ============================================== whose list is it ============
def test_a_doctor_sees_their_own_before_the_clinics(clinic):
    """The request in one assertion."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_clinic(clinic, "complaint", "حرارة|Fever")
        _set_doctor(clinic, clinic["ids"]["doctor"], "complaint", "زلال|Albuminuria")

        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert [r["ar"] for r in _phrases().for_user(doctor, "complaint")] == ["زلال"]


def test_two_doctors_keep_two_lists(clinic):
    """A diabetes clinic and a neonatal one, on one installation."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam", "القدم السكري|Diabetic foot")
        _set_doctor(clinic, clinic["ids"]["admin"], "exam", "اليافوخ مسطح|Flat fontanelle")

        phrases = _phrases()
        mine = phrases.for_user(db.session.get(User, clinic["ids"]["doctor"]), "exam")
        theirs = phrases.for_user(db.session.get(User, clinic["ids"]["admin"]), "exam")
        assert [r["ar"] for r in mine] == ["القدم السكري"]
        assert [r["ar"] for r in theirs] == ["اليافوخ مسطح"]


def test_a_doctor_with_no_list_gets_the_clinics(clinic):
    """Blank means "use the clinic's", not "I have none" — a doctor who has
    never opened the screen still finds phrases under their fingers."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_clinic(clinic, "complaint", "حرارة|Fever")
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert [r["ar"] for r in _phrases().for_user(doctor, "complaint")] == ["حرارة"]


def test_a_clinic_with_no_list_gets_the_built_in_ones(clinic):
    """A fresh install is not an empty screen."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        for field in _phrases().FIELDS:
            assert _phrases().for_user(doctor, field), f"{field} came back empty"


def test_the_clinics_list_is_not_the_admins_own(clinic):
    """A bug found while moving this code. The settings screen called the
    doctor-aware reader, so an admin who had phrases of their own was shown
    them under a heading that said "the clinic's" — and saving wrote their
    personal list over the clinic's."""
    with clinic["app"].app_context():
        _set_clinic(clinic, "exam", "لستة العيادة|The clinic list")
        _set_doctor(clinic, clinic["ids"]["admin"], "exam", "لستتي أنا|My own")

        rows = _phrases().clinic_phrases("exam")
        assert [r["ar"] for r in rows] == ["لستة العيادة"]


# ============================================== the codes ===================
def test_only_phrases_with_a_code_can_be_typed(clinic):
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam",
                    "نورمال|فحص طبيعي تماماً|Entirely normal\nالحلق محتقن|Throat congested")

        codes = _phrases().codes(db.session.get(User, clinic["ids"]["doctor"]))["exam"]
        assert codes == {"نورمال": "فحص طبيعي تماماً"}


def test_the_code_writes_the_sentence_in_the_language_on_screen(clinic):
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam", "n|طبيعي|Normal")
        codes = _phrases().codes(db.session.get(User, clinic["ids"]["doctor"]), "en")
        assert codes["exam"] == {"n": "Normal"}


# ============================================== the screen ==================
def test_a_doctor_can_open_and_save_their_own_phrases(clinic):
    from app.models import User

    db = clinic["db"]
    doc = clinic["sign_in"]("doc")
    assert doc.get("/visits/phrases").status_code == 200

    doc.post("/visits/phrases", data={
        "visit_complaint_chips": "سكر|ارتفاع سكر|High sugar",
        "visit_exam_chips": "", "visit_plan_chips": "",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        saved = db.session.get(User, clinic["ids"]["doctor"]).visit_complaint_chips
        assert saved == "سكر|ارتفاع سكر|High sugar"


def test_clearing_a_field_goes_back_to_the_clinics_list(clinic):
    """The way out. Without it, a doctor who empties the box has no phrases at
    all and no way to discover why."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_clinic(clinic, "exam", "لستة العيادة|The clinic list")
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam", "بتاعي|Mine")

    clinic["sign_in"]("doc").post("/visits/phrases", data={
        "visit_complaint_chips": "", "visit_exam_chips": "",
        "visit_plan_chips": "",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert doctor.visit_exam_chips is None
        assert [r["ar"] for r in _phrases().for_user(doctor, "exam")] == ["لستة العيادة"]


def test_the_visit_screen_shows_this_doctors_phrases(clinic):
    """The whole point: what is under the doctor's hand while the child is in
    front of them."""
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "complaint",
                    "سكر|ارتفاع سكر متكرر|Recurrent hyperglycaemia")

    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").data.decode()
    assert "ارتفاع سكر متكرر" in page
    assert "/visits/phrases" in page, "no way to reach the screen from the visit"


def test_the_visit_screen_carries_the_codes_to_the_browser(clinic):
    """The expansion happens as the doctor types, so the codes have to be on
    the page — a round trip to the server per keystroke is not typing."""
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam", "نورمال|فحص طبيعي|Normal")

    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").data.decode()
    assert '"codes"' in page
    assert "expand('exam', 'exam'" in page


def test_the_plan_box_has_phrases_too(clinic):
    """It had none, and it is where the repetition actually is: the same six
    sentences, typed out, all day."""
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").data.decode()
    assert "addPlan(" in page


# ============================================== what must not happen ========
def test_saving_the_profile_does_not_wipe_a_doctors_phrases(clinic):
    """The profile page used to hold a second copy of this editor. Removing it
    without removing the write would have cleared every doctor's phrases the
    next time they changed their photo — the form no longer posts the fields,
    and a missing field read as "clear it"."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        _set_doctor(clinic, clinic["ids"]["doctor"], "exam", "بتاعي|Mine")

    clinic["sign_in"]("doc").post("/profile", data={
        "full_name": "د. أحمد", "language": "ar", "theme": "light",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(User, clinic["ids"]["doctor"]).visit_exam_chips \
            == "بتاعي|Mine"
