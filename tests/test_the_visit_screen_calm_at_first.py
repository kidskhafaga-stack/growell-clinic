"""شاشة الكشف — أول صفحة هادية، ومفيش حاجة اتشالت.

صاحب العيادة على شاشة الكشف: *«الشاشة طولت قوي … أنا عايز الطبيب ما
يتشتتش في الصفحة الأولى، وخلي بالك علشان مفيش حاجة تبوظ»*.

* **التحاليل المطلوبة من الزيارة اللي فاتت** مطوية في سطر واحد بينوّر
  بعددها — ولو فيه ملف وصل على الواتساب بيقول كده، والطلب اللي عليه الملف
  بيتفتح لوحده؛ والفورم جوّه زي ما هي؛
* **تعليمات التمريض، المتابعة، الرعاية بعد الزيارة، تحويل للطوارئ، تحويل
  لطبيب** بقوا صف بلاطات؛ كل بلاطة بتفتح صندوقها، واللي فيها حاجة بتقول
  على البلاطة («اتبعت»، تاريخ، «اتحوّل») — والمحوّل ليه بتنادي وبتفتح
  لوحدها؛
* **تلخيص الزيارة بالـ AI** في شريط لوحده تحت، مش مع التحويل؛
* **الترس** اللي كان بيودّي للإعدادات بقى «عدّل العبارات» مكتوبة.
"""
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _url(clinic, tail="/record"):
    return f"/visits/{clinic['ids']['visit']}{tail}"


def _earlier_orders(clinic, whatsapp=True):
    """Two tests asked for at an earlier visit, still without a result; the
    family sent one of them on WhatsApp."""
    from app.models import PatientAttachment, Visit, VisitInvestigation
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        old = Visit(patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
                    visit_date=local_today() - timedelta(days=10))
        db.session.add(old)
        db.session.flush()
        cbc = VisitInvestigation(visit_id=old.id, patient_id=old.patient_id, kind="lab",
                                 name="صورة دم كاملة", status="requested")
        urine = VisitInvestigation(visit_id=old.id, patient_id=old.patient_id, kind="lab",
                                   name="تحليل بول", status="requested")
        db.session.add_all([cbc, urine])
        db.session.flush()
        if whatsapp:
            db.session.add(PatientAttachment(patient_id=old.patient_id, visit_id=old.id,
                                             investigation_id=cbc.id, filename="cbc.jpg",
                                             original_name="cbc.jpg", kind="result",
                                             source="whatsapp"))
        db.session.commit()
        return cbc.id, urine.id


def _tag(page, marker):
    """The opening tag that carries ``marker``."""
    i = page.index(marker)
    return page[page.rindex("<", 0, i):page.index(">", i) + 1]


def test_the_earlier_tests_fold_into_one_line_that_says_how_many(clinic):
    cbc, urine = _earlier_orders(clinic)
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    fold = _tag(page, "data-pending-fold")
    assert fold.startswith("<details") and " open" not in fold, "folded at first"
    assert re.search(r"data-pending-count>\s*2\s*<", page)
    assert "data-pending-whatsapp" in page, "a file came on WhatsApp — said on the line"
    assert " open" in _tag(page, f'data-pending-item="{cbc}"'), "the one with the file opens"
    assert " open" not in _tag(page, f'data-pending-item="{urine}"')
    # Nothing inside was lost: both orders and their names are still there.
    assert "صورة دم كاملة" in page and "تحليل بول" in page


def test_no_whatsapp_badge_without_a_whatsapp_file(clinic):
    _earlier_orders(clinic, whatsapp=False)
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert "data-pending-fold" in page and "data-pending-whatsapp" not in page


def test_nothing_pending_means_no_fold(clinic):
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert "data-pending-fold" not in page


def test_what_leaves_the_room_is_one_row_of_tiles(clinic):
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    zone = _tag(page, "data-after-zone")
    assert "open: &#34;&#34;" in zone or 'open: ""' in zone, "all folded at first"
    for tile in ("nurse", "followup", "er"):
        assert f'data-after-tile="{tile}"' in page
        assert f'data-after-panel="{tile}"' in page
    # The boxes are still inside — only folded.
    for mark in ("data-followup-save", 'name="nurse_instructions"'):
        if mark in page:
            assert page.index(mark) > page.index("data-after-zone")


def test_a_tile_says_what_it_already_holds(clinic):
    from app.models import Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        v = db.session.get(Visit, clinic["ids"]["visit"])
        v.nurse_instructions = "بخاخة كل ٦ ساعات"
        db.session.commit()
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    nurse = page[page.index('data-after-tile="nurse"'):]
    nurse = nurse[:nurse.index("</button>")]
    assert "at-state" in nurse


def test_a_child_referred_to_me_calls_and_opens_by_itself(clinic):
    from app.models import Referral, User, Visit
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        u = User(username="cardio", full_name="منى سامي", role="doctor", is_active=True)
        u.set_password("secret")
        db.session.add(u)
        db.session.commit()
        cardio = u.id
    clinic["sign_in"]("doc").post(_url(clinic, "/refer-doctor"), data={
        "where": "inside", "to_doctor_id": cardio, "reason": "لغط في القلب"})
    with clinic["app"].app_context():
        v = Visit(patient_id=clinic["ids"]["child"], doctor_id=cardio, visit_date=local_today())
        db.session.add(v)
        db.session.commit()
        vid, rid = v.id, Referral.query.one().id
    page = clinic["sign_in"]("cardio").get(f"/visits/{vid}/record").get_data(as_text=True)
    assert "is-calling" in _tag(page, 'data-after-tile="docref"')
    zone = _tag(page, "data-after-zone")
    assert "docref" in zone.split("toggle(k)")[0], "opens on the referral"
    assert f'data-docref-reply="{rid}"' in page

    # The one who referred sees a quiet tile with the count, folded.
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert "is-calling" not in _tag(page, 'data-after-tile="docref"')
    assert "docref" not in _tag(page, "data-after-zone").split("toggle(k)")[0]


def test_the_ai_summary_has_its_own_strip_below_the_tiles(clinic):
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert "data-ai-strip" in page
    assert page.index("data-ai-strip") > page.index("data-after-zone")
    # Not inside any of the referral boxes.
    last_panel = page.rindex("data-after-panel=")
    between = page[last_panel:page.index("data-ai-strip")]
    assert between.count("<div") <= between.count("</div>"), "outside the folded boxes"


def test_the_gear_became_words(clinic):
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    chips = re.findall(r"<a [^>]*data-edit-phrases[^>]*>.*?</a>", page, re.S)
    assert chips, "the phrases door is still there"
    for chip in chips:
        assert "bi-gear" not in chip and "عدّل العبارات" in chip


def test_the_dental_chart_button_only_with_dentistry(clinic, monkeypatch):
    """«لو الأسنان مش متفعلة مش هتظهر؟» — صح، مش بتظهر."""
    from app.utils import facility

    doc = clinic["sign_in"]("doc")
    real = facility.module_enabled
    monkeypatch.setattr(facility, "module_enabled",
                        lambda m: False if m == "dentistry" else real(m))
    page = doc.get(_url(clinic)).get_data(as_text=True)
    assert "bi-grid-3x3" not in page
    monkeypatch.setattr(facility, "module_enabled",
                        lambda m: True if m == "dentistry" else real(m))
    page = doc.get(_url(clinic)).get_data(as_text=True)
    assert "bi-grid-3x3" in page
