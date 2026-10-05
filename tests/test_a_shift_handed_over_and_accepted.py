"""التسليم بين الورديات وبين الأقسام — GAHAR `ACT.08` / `GSR.04`.

* **(أ) الشكل شكل المستشفى** — SBAR أو ISBAR أو I-PASS، لكل نوع لوحده،
  ومكتوب على التسليم وقت ما اتعمل؛
* **(ب) بين الورديات وبين الأقسام** — ورقة القسم، و«كل الأقسام» لمقيم
  الليل، والطفل اللي اتنقل لقسم تاني بيستناه القسم ده يستلمه؛
* **فرصة للسؤال والرد** — والاستلام ما بيتقفلش وفيه سؤال من غير رد؛
* **دليل ٤** — الكارت متملي من الملف ومتصوّر زي ما اتسلّم؛
* **دليل ٥** — التقرير بيعدّ، وما بيحكمش إلا برقم المستشفى.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def wards(clinic):
    """قسمين، وطفلين في الداخلي، وممرضتين وطبيبين."""
    from app.models import Patient, Setting, User
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as place
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        for username, role, name in (("nurse", "nursing", "الممرضة"),
                                     ("nurse2", "nursing", "ممرضة تانية"),
                                     ("doc2", "doctor", "د. تاني")):
            user = User(username=username, full_name=name, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
        beds = {}
        for unit_name, kind, bed_names in (("الداخلي", "ward", ("س١", "س٢", "س٣")),
                                           ("العناية", "icu", ("ع١",))):
            unit = Unit(name=unit_name, kind=kind)
            db.session.add(unit)
            db.session.flush()
            space = Space(unit_id=unit.id, name="غرفة", kind="room")
            db.session.add(space)
            db.session.flush()
            for order, name in enumerate(bed_names):
                bed = Bed(space_id=space.id, name=name, sort_order=order)
                db.session.add(bed)
                db.session.flush()
                beds[name] = bed.id
            clinic[f"unit_{kind}"] = unit.id
        stays = {}
        for number, (name, bed) in enumerate((("سلمى", "س١"), ("يوسف", "س٢"))):
            child = Patient(patient_number=f"H{number}", full_name=name,
                            gender="female", is_active=True,
                            allergies="بنسلين" if number == 0 else None,
                            date_of_birth=local_today() - timedelta(days=900))
            db.session.add(child)
            db.session.flush()
            row = place.admit(child, db.session.get(Bed, beds[bed]),
                              reason="التهاب رئوي" if number == 0 else None)
            stays[name] = row.id
        db.session.commit()
        clinic["beds"] = beds
        clinic["stays"] = stays
        clinic["users"] = {u.username: u.id for u in User.query.all()}
    return clinic


def _hand(c, who="nurse", discipline="nursing", unit="ward", **form):
    unit_id = c[f"unit_{unit}"] if unit else 0
    data = {"unit_id": str(unit_id), "discipline": discipline, **form}
    return c["sign_in"](who).post("/beds/handover/new", data=data)


def _last():
    from app.models import Handover

    return Handover.query.order_by(Handover.id.desc()).first()


def test_the_sheet_is_filled_from_the_record_and_kept_as_it_was_said(wards):
    from app.models import Patient

    nurse = wards["sign_in"]("nurse")
    page = nurse.get(f"/beds/handover/new?unit={wards['unit_ward']}"
                     "&discipline=nursing").get_data(as_text=True)
    assert page.count("data-handover-card") == 2
    for piece in ("سلمى", "يوسف", "بنسلين", "التهاب رئوي", "H0"):
        assert piece in page, piece

    salma = wards["stays"]["سلمى"]
    answer = _hand(wards, **{f"watch_{salma}": "راقبي التنفّس كل ساعة"})
    with wards["app"].app_context():
        row = _last()
        assert answer.headers["Location"].endswith(f"/beds/handover/{row.id}")
        assert (row.method, row.discipline, len(row.items)) == ("sbar", "nursing", 2)
        mine = next(i for i in row.items if i.admission_id == salma)
        assert mine.watch == "راقبي التنفّس كل ساعة"
        assert mine.card["allergies"] == "بنسلين"
        # The record moves on; the handover still says what was handed.
        Patient.query.filter_by(patient_number="H0").one().allergies = "لا شيء"
        wards["db"].session.commit()
        handover_id = row.id
    view = nurse.get(f"/beds/handover/{handover_id}").get_data(as_text=True)
    assert "بنسلين" in view and "راقبي التنفّس كل ساعة" in view


def test_whoever_handed_it_over_cannot_accept_it_and_the_right_side_can(wards):
    _hand(wards)
    with wards["app"].app_context():
        handover_id = _last().id
    for who in ("nurse", "doc"):
        wards["sign_in"](who).post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        assert _last().accepted_at is None, "giver, and a doctor for nursing"
    wards["sign_in"]("nurse2").post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        row = _last()
        assert row.accepted_by == wards["users"]["nurse2"]
        assert row.minutes_to_accept() is not None


def test_a_question_holds_the_acceptance_until_it_is_answered(wards):
    _hand(wards)
    with wards["app"].app_context():
        row = _last()
        handover_id, item_id = row.id, row.items[0].id
    receiver = wards["sign_in"]("nurse2")
    wards["sign_in"]("nurse").post(f"/beds/handover/item/{item_id}/ask",
                                   data={"question": "سؤالي لنفسي"})
    receiver.post(f"/beds/handover/item/{item_id}/ask",
                  data={"question": "آخر حرارة كانت إمتى؟"})
    receiver.post(f"/beds/handover/item/{item_id}/answer", data={"answer": "مش أنا"})
    receiver.post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        row = _last()
        assert row.items[0].question == "آخر حرارة كانت إمتى؟"
        assert row.items[0].answer is None and row.accepted_at is None
    page = receiver.get(f"/beds/handover/{handover_id}").get_data(as_text=True)
    assert "data-unanswered" in page
    wards["sign_in"]("nurse").post(f"/beds/handover/item/{item_id}/answer",
                                   data={"answer": "الساعة ٦"})
    receiver.post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        assert _last().accepted_by == wards["users"]["nurse2"]


def test_each_hospital_uses_its_own_tool_for_each_kind(wards):
    from app.models import Handover

    boss = wards["sign_in"]("boss")
    boss.post("/beds/handover/settings",
              data={"method_medical": "ipass", "method_nursing": "isbar",
                    "method_transfer": "sbar"})
    # A non-admin does not change the hospital's tool.
    wards["sign_in"]("doc").post("/beds/handover/settings",
                                 data={"method_medical": "sbar"})
    page = wards["sign_in"]("doc").get(
        f"/beds/handover/new?unit={wards['unit_ward']}&discipline=medical"
    ).get_data(as_text=True)
    assert 'data-section="illness"' in page and 'data-section="awareness"' in page

    # I-PASS: every child gets an illness severity, and the receiver
    # summarises before accepting.
    _hand(wards, who="doc", discipline="medical")
    with wards["app"].app_context():
        assert Handover.query.count() == 0
    stays = wards["stays"]
    _hand(wards, who="doc", discipline="medical",
          **{f"severity_{stays['سلمى']}": "watcher",
             f"severity_{stays['يوسف']}": "stable"})
    with wards["app"].app_context():
        row = _last()
        assert row.method == "ipass"
        assert {i.severity for i in row.items} == {"watcher", "stable"}
        handover_id = row.id
    doc2 = wards["sign_in"]("doc2")
    doc2.post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        assert _last().accepted_at is None
    doc2.post(f"/beds/handover/{handover_id}/accept", data={"synthesis": "1"})
    with wards["app"].app_context():
        assert _last().synthesis is True

    _hand(wards)
    with wards["app"].app_context():
        assert _last().method == "isbar"
    view = wards["sign_in"]("nurse").get(f"/beds/handover/{handover_id}")
    assert 'data-section="illness"' in view.get_data(as_text=True)
    # Changing the tool later does not rewrite a handover already given.
    boss.post("/beds/handover/settings", data={"method_medical": "sbar"})
    with wards["app"].app_context():
        assert wards["db"].session.get(Handover, handover_id).method == "ipass"


def test_a_child_moved_to_another_department_waits_to_be_accepted_there(wards):
    from app.models import Admission
    from app.models.place import Bed
    from app.utils import beds as place

    salma = wards["stays"]["سلمى"]
    with wards["app"].app_context():
        db = wards["db"]
        from app.models import User

        nurse = db.session.get(User, wards["users"]["nurse"])
        # Within the same department: the same team has the child.
        place.move(db.session.get(Admission, salma),
                   db.session.get(Bed, wards["beds"]["س٣"]), user=nurse)
        db.session.commit()
        assert _last() is None
    wards["sign_in"]("nurse").post(f"/beds/admission/{salma}/move",
                                   data={"bed_id": str(wards["beds"]["ع١"]),
                                         "note": "محتاجة أكسجين عالي"})
    with wards["app"].app_context():
        row = _last()
        assert (row.occasion, row.unit_id, row.from_unit_id) == (
            "transfer", wards["unit_icu"], wards["unit_ward"])
        assert row.items[0].watch == "محتاجة أكسجين عالي"
        assert row.items[0].card["bed"]["ar"] == "ع١"
        handover_id = row.id
    watch = wards["sign_in"]("boss").get("/beds/watch").get_data(as_text=True)
    assert f'data-handover-waiting-row="{handover_id}"' in watch
    # Whoever moved the child does not accept them; anybody receiving does.
    wards["sign_in"]("nurse").post(f"/beds/handover/{handover_id}/accept")
    wards["sign_in"]("doc").post(f"/beds/handover/{handover_id}/accept")
    with wards["app"].app_context():
        assert _last().accepted_by == wards["users"]["doc"]


def test_one_open_handover_per_department_and_the_giver_may_take_it_back(wards):
    from app.models import Handover

    _hand(wards)
    _hand(wards, who="nurse2")
    with wards["app"].app_context():
        assert Handover.query.count() == 1
        handover_id = _last().id
    wards["sign_in"]("nurse2").post(f"/beds/handover/{handover_id}/withdraw")
    with wards["app"].app_context():
        assert Handover.query.count() == 1
    wards["sign_in"]("nurse").post(f"/beds/handover/{handover_id}/withdraw")
    with wards["app"].app_context():
        assert Handover.query.count() == 0


def test_the_night_resident_hands_over_every_department_at_once(wards):
    from app.models import Admission, Patient
    from app.models.place import Bed
    from app.utils import beds as place
    from app.utils.clock import local_today

    with wards["app"].app_context():
        db = wards["db"]
        child = Patient(patient_number="H9", full_name="مريم", gender="female",
                        is_active=True,
                        date_of_birth=local_today() - timedelta(days=60))
        db.session.add(child)
        db.session.flush()
        place.admit(child, db.session.get(Bed, wards["beds"]["ع١"]))
        db.session.commit()
    _hand(wards, who="doc", discipline="medical", unit=None)
    with wards["app"].app_context():
        row = _last()
        assert row.unit_id is None and len(row.items) == 3
    page = wards["sign_in"]("boss").get("/beds/handover").get_data(as_text=True)
    assert 'data-handover-unit="0"' in page and "data-open-handover" in page


def test_the_report_counts_and_judges_only_against_the_hospital_s_number(wards):
    from app.utils import handover
    from app.utils.clock import local_today

    _hand(wards)
    with wards["app"].app_context():
        data = handover.report(local_today(), local_today())
        (group,) = data["groups"]
        assert (group["count"], group["accepted"], group["kind"]) == (1, 0, "nursing")
        assert data["short_days"] == [] and len(data["waiting"]) == 1
    page = wards["sign_in"]("boss").get("/beds/handover/report").get_data(as_text=True)
    assert "data-no-per-day" in page

    wards["sign_in"]("boss").post("/beds/handover/settings",
                                  data={"per_day_nursing": "3"})
    with wards["app"].app_context():
        short = handover.report(local_today(), local_today())["short_days"]
        # Both departments are short — the one nobody handed over too.
        assert {(s["unit"].id, s["done"], s["expected"]) for s in short} == {
            (wards["unit_ward"], 1, 3), (wards["unit_icu"], 0, 3)}


def test_the_doors_lead_to_it(wards):
    boss = wards["sign_in"]("boss")
    assert "data-to-handovers" in boss.get("/beds/").get_data(as_text=True)
    page = boss.get("/beds/handover").get_data(as_text=True)
    assert "data-to-handover-new" in page and "data-to-handover-report" in page
    assert "data-handover-settings" in page
    assert "data-handover-settings" not in wards["sign_in"]("nurse").get(
        "/beds/handover").get_data(as_text=True)


def test_a_department_closed_to_its_team_keeps_its_handover_too(wards):
    from app.models import User
    from app.models.place import Unit
    from app.utils import unit_access

    with wards["app"].app_context():
        db = wards["db"]
        unit_access.set_team(db.session.get(Unit, wards["unit_ward"]),
                             [wards["users"]["nurse"]])
        db.session.commit()
        assert db.session.get(User, wards["users"]["nurse2"]) is not None
    url = f"/beds/handover/new?unit={wards['unit_ward']}&discipline=nursing"
    assert wards["sign_in"]("nurse2").get(url).status_code == 403
    assert wards["sign_in"]("nurse").get(url).status_code == 200
