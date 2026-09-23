"""مكان واحد في الملف لأوامر الدوا — GAHAR `MMS.11` (ب).

> b) Uniform location in the patient's medical record to order/prescribe
> medications.

**التبويب كان بيقول نص الحكاية.** الروشتات والأدوية اللي في البيت كانوا في
مكان واحد، **وأوامر الإقامة كانت على شاشة الإقامة بس**. دكتور بيشوف الطفل
في العيادة بعد أسبوع من خروجه ما كانش يعرف من الملف اتدّاله إيه جوّه.

فالتبويب بقى المكان الواحد اللي بيتقري منه — **والكتابة لسه في مكانها**:
الأمر الداخلي على الإقامة لأن الممرضة بتدّي منه، والروشتة للبيت. ومن
التبويب زرار لكل واحد، والمكان بيتحدّد بحال الطفل.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """قسم فيه سرير، والإقامة مفتوحة للموديول."""
    from app.blueprints.beds.routes import MODULE
    from app.models import Bed, Setting, Space, Unit

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        unit = Unit(name="الداخلي", kind="ward")
        db.session.add(unit)
        db.session.flush()
        room = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        db.session.add(room)
        db.session.flush()
        beds = [Bed(space_id=room.id, name=f"سرير {i}") for i in (1, 2)]
        db.session.add_all(beds)
        db.session.commit()
        yield {"beds": [b.id for b in beds]}


def _admit(clinic, bed_id, patient_id=None):
    from app.models import Bed, Patient, User
    from app.utils import beds as wardutils

    db = clinic["db"]
    kid = db.session.get(Patient, patient_id or clinic["ids"]["child"])
    doc = User.query.filter_by(username="doc").one()
    stay = wardutils.admit(kid, db.session.get(Bed, bed_id), user=doc,
                           doctor_id=doc.id)
    db.session.flush()
    return stay, doc


def _order(stay, doc, name, **kw):
    from app.utils import drug_round

    kw.setdefault("every_hours", 8)
    return drug_round.order(stay, name, user=doc, dose="250 mg", **kw)


def _file(clinic, user="boss"):
    page = clinic["sign_in"](user).get(f"/patients/{clinic['ids']['child']}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    tab = html.split("x-show=\"tab==='prescriptions'\"")[1]
    return html, tab.split('class="gc-tab-panel"')[0]


# ============ القراية ============
def test_an_inpatient_order_is_in_the_file(clinic, ward):
    """**ده الحتة كلها**: أمر اتكتب على الإقامة بيبان في تبويب الملف."""
    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        row = _order(stay, doc, "Ceftriaxone")
        clinic["db"].session.commit()
        order_id, doc_name = row.id, doc.full_name

    _html, tab = _file(clinic)
    assert f'data-inpatient-order="{order_id}"' in tab
    assert "Ceftriaxone" in tab
    # (هـ)(١١) — هوية الطبيب على كل أمر.
    assert doc_name in tab


def test_it_is_still_there_after_the_child_goes_home(clinic, ward):
    """**ودي اللحظة اللي كان ناقص فيها**: الطفل خرج، والدكتور بيشوفه في
    العيادة. قبل كده الأمر كان على شاشة إقامة محدّش هيفتحها."""
    from app.utils import beds as wardutils

    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        _order(stay, doc, "Amoxicillin")
        wardutils.discharge(stay, "home", user=doc)
        clinic["db"].session.commit()

    _html, tab = _file(clinic)
    assert "Amoxicillin" in tab


def test_a_stopped_order_says_when_and_why(clinic, ward):
    """(د) إيقاف الأمر — **بسببه**، مش بيختفي."""
    from app.utils import drug_round

    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        row = _order(stay, doc, "Metronidazole")
        drug_round.stop(row, user=doc, reason="كورس خلص")
        clinic["db"].session.commit()
        order_id = row.id

    _html, tab = _file(clinic)
    line = tab.split(f'data-inpatient-order="{order_id}"')[1].split("</tr>")[0]
    assert "كورس خلص" in line


def test_running_orders_come_first(clinic, ward):
    """الشغّال فوق: ده اللي حد بيدوّر عليه وهو فاتح الملف."""
    from app.utils import drug_round

    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        running = _order(stay, doc, "Paracetamol")
        clinic["db"].session.flush()
        stopped = _order(stay, doc, "Ibuprofen")
        drug_round.stop(stopped, user=doc, reason="حرارة نزلت")
        clinic["db"].session.commit()
        first, second = running.id, stopped.id

    _html, tab = _file(clinic)
    assert tab.index(f'data-inpatient-order="{first}"') < \
        tab.index(f'data-inpatient-order="{second}"')


def test_a_prn_order_says_so(clinic, ward):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        _order(stay, doc, "Ondansetron", every_hours=None, is_prn=True,
               min_gap_hours=6)
        clinic["db"].session.commit()

    _html, tab = _file(clinic)
    line = tab.split("Ondansetron")[1].split("</tr>")[0]
    assert ar["meds"]["prn"] in line
    assert "≥6h" in line


def test_only_this_child_s_orders(clinic, ward):
    from app.models import Patient

    with clinic["app"].app_context():
        other = Patient(full_name="طفل تاني", patient_number="P-OTHER",
                        gender="female", date_of_birth=date(2023, 5, 5))
        clinic["db"].session.add(other)
        clinic["db"].session.flush()
        stay, doc = _admit(clinic, ward["beds"][1], patient_id=other.id)
        _order(stay, doc, "Vancomycin")
        clinic["db"].session.commit()

    _html, tab = _file(clinic)
    assert "Vancomycin" not in tab
    assert "data-inpatient-orders" not in tab


def test_a_clinic_with_no_stays_draws_no_empty_section(clinic):
    """قسم فاضي في كل ملف أطفال أثاث مش معلومة."""
    _html, tab = _file(clinic)
    assert "data-inpatient-orders" not in tab


# ============ الكتابة ============
def test_an_admitted_child_gets_a_button_to_the_stay_s_order_form(clinic, ward):
    """**من هنا بيتكتب، بس مش هنا بيتخزّن**: الأمر الداخلي على الإقامة،
    لأن الممرضة بتدّي منه والجرعات بتتسجّل عليه."""
    with clinic["app"].app_context():
        stay, _doc = _admit(clinic, ward["beds"][0])
        clinic["db"].session.commit()
        stay_id = stay.id

    _html, tab = _file(clinic)
    button = tab.split("data-order-for-stay")[1].split("</a>")[0]
    assert f"/beds/admission/{stay_id}#medicines" in button


def test_a_child_at_home_gets_no_stay_button(clinic, ward):
    _html, tab = _file(clinic)
    assert "data-order-for-stay" not in tab


def test_the_stay_page_has_the_place_the_button_points_at(clinic, ward):
    """زرار بيودّي على مكان مش موجود بيوقف في أول الصفحة — ويخلّي اللي
    ضغط يدوّر."""
    with clinic["app"].app_context():
        stay, _doc = _admit(clinic, ward["beds"][0])
        clinic["db"].session.commit()
        stay_id = stay.id

    html = clinic["sign_in"]("boss").get(
        f"/beds/admission/{stay_id}").get_data(as_text=True)
    anchor = html.split('id="medicines"')
    assert len(anchor) == 2
    # وهو فعلاً الكارت اللي فيه فورم الأمر.
    card = anchor[1].split('<div class="card')[0]
    assert f"/beds/admission/{stay_id}/medication" in card


# ============ الحدود ============
def test_the_front_desk_does_not_read_a_child_s_drugs(clinic, ward):
    """الأدوية معلومة إكلينيكية — ورا نفس الصلاحية اللي الروشتات وراها."""
    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        _order(stay, doc, "Phenytoin")
        clinic["db"].session.commit()

    page = clinic["sign_in"]("desk").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "Phenytoin" not in page


def test_the_file_asks_once_not_once_per_order(clinic, ward):
    """**استعلام واحد للأوامر، والكاتب معاهم.** طفل عليه عشرين أمر لازم
    الملف يكلّف نفس اللي بيكلّفه طفل عليه أمر واحد."""
    from sqlalchemy import event

    with clinic["app"].app_context():
        stay, doc = _admit(clinic, ward["beds"][0])
        _order(stay, doc, "Drug 0")
        clinic["db"].session.commit()
        engine = clinic["db"].engine
        stay_id, doc_id = stay.id, doc.id

    def count():
        seen = []
        hook = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", hook)
        try:
            _file(clinic)
        finally:
            event.remove(engine, "before_cursor_execute", hook)
        return len(seen)

    count()
    small = count()
    with clinic["app"].app_context():
        from app.models import Admission, User

        stay = clinic["db"].session.get(Admission, stay_id)
        doc = clinic["db"].session.get(User, doc_id)
        for i in range(1, 20):
            _order(stay, doc, f"Drug {i}")
        clinic["db"].session.commit()
    big = count()
    assert big == small, (small, big)


def test_every_word_is_written_in_both_languages():
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    assert set(ar["med_orders"]) == set(en["med_orders"])
    for key in ar["med_orders"]:
        assert ar["med_orders"][key].strip(), key
        assert en["med_orders"][key].strip(), key
