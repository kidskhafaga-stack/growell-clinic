"""زيارة بتتلاقى — مش بتتقلّب عليها.

*"شاشة visits محتاجه فلترة بأسم الطبيب «بحث» او اسم المريض «بحث» التاريخ
من - الى، لان فى مستشفى بيجلها الاف الزيارات مش طبيعي ان الناس تقعد تدور
على زيارة."*

القايمة كانت صفحات بالترتيب وبس. فالفلاتر هي التلاتة اللي حد فاكرهم:
**الطفل** (بنفس البحث اللي في كل شاشة مرضى)، **والطبيب** (بالبحث مش
بقايمة منسدلة — `test_doctor_picker` بيمنعها)، **والفترة**.

**وقفل الخصوصية بيفضل فوقهم**: طبيب مقفول على زياراته ما يقدرش يوسّع
اللي بيشوفه من الفلتر.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """تلات زيارات: طفلين، طبيبين، وتواريخ مختلفة."""
    from app.models import Patient, User, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").one()
        other = User(username="doc2", full_name="د. منى", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        kid = Patient(patient_number="P-FIND", full_name="ياسين المصري",
                      gender="male", date_of_birth=date(2024, 3, 1),
                      is_active=True)
        db.session.add(kid)
        db.session.flush()
        today = local_today()
        old = Visit(patient_id=kid.id, doctor_id=other.id,
                    visit_date=today - timedelta(days=40))
        recent = Visit(patient_id=kid.id, doctor_id=doc.id,
                       visit_date=today - timedelta(days=2))
        db.session.add_all([old, recent])
        db.session.commit()
        ids = {"doc": doc.id, "other": other.id, "kid": kid.id,
               "old": old.id, "recent": recent.id,
               "fixture_visit": clinic["ids"]["visit"], "today": today}
    # بره الـcontext: `yield` جوّاه بيخلّي كل طلبات الاختبار تتشارك جلسة
    # واحدة — وده مش اللي بيحصل على جهاز العيادة.
    yield ids


def _ids(clinic, query_string, user="boss"):
    import re

    page = clinic["sign_in"](user).get("/visits/?" + query_string)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    return {int(v) for v in re.findall(r'/visits/(\d+)(?:/view)?"', html)}, html


def test_no_filter_shows_everything(clinic, ward):
    seen, _ = _ids(clinic, "")
    assert {ward["old"], ward["recent"], ward["fixture_visit"]} <= seen


def test_by_the_child_s_name(clinic, ward):
    seen, _ = _ids(clinic, "q=ياسين")
    assert seen == {ward["old"], ward["recent"]}


def test_by_the_file_number_too(clinic, ward):
    """**نفس البحث اللي في كل شاشة مرضى** — مش نسخة تانية منه."""
    seen, _ = _ids(clinic, "q=P-FIND")
    assert seen == {ward["old"], ward["recent"]}


def test_by_the_doctor(clinic, ward):
    seen, _ = _ids(clinic, f"doctor_id={ward['other']}")
    assert seen == {ward["old"]}


def test_by_a_date_range(clinic, ward):
    today = ward["today"]
    frm = (today - timedelta(days=7)).isoformat()
    seen, _ = _ids(clinic, f"from={frm}&to={today.isoformat()}")
    assert ward["recent"] in seen
    assert ward["old"] not in seen


def test_the_end_of_the_range_is_a_real_limit(clinic, ward):
    """**الحدّين، مش الأول بس.** فترة بتنتهي الأسبوع اللي فات لازم تسيب
    زيارة امبارح بره — ومن غير الاختبار ده، `to` كان ممكن يتشال وكل
    اختبار تاني ينجح، لأن مفيش زيارة بعد النهارده أصلاً."""
    today = ward["today"]
    frm = (today - timedelta(days=45)).isoformat()
    to = (today - timedelta(days=30)).isoformat()
    seen, _ = _ids(clinic, f"from={frm}&to={to}")
    assert seen == {ward["old"]}


def test_a_range_typed_backwards_is_read_the_right_way(clinic, ward):
    """«من ١٥ لـ١» غلطة كتابة مش طلب فاضي — والقايمة الفاضية شكلها زي
    «مفيش زيارات»."""
    today = ward["today"]
    frm = (today - timedelta(days=7)).isoformat()
    seen, _ = _ids(clinic, f"from={today.isoformat()}&to={frm}")
    assert ward["recent"] in seen
    assert ward["old"] not in seen


def test_filters_combine(clinic, ward):
    seen, _ = _ids(clinic, f"q=ياسين&doctor_id={ward['doc']}")
    assert seen == {ward["recent"]}


def test_a_mistyped_date_means_no_limit_not_an_error(clinic, ward):
    seen, _ = _ids(clinic, "from=not-a-date")
    assert {ward["old"], ward["recent"]} <= seen


def test_a_locked_doctor_cannot_widen_the_list_from_the_filter(clinic, ward):
    """**الشرطين بيتجمعوا بـ«و»، و«و» ما بتوسّعش أبداً.** طبيب مقفول على
    زياراته بيختار طبيب تاني من الفلتر — المفروض يشوف ولا حاجة، مش
    زيارات زميله."""
    seen, _ = _ids(clinic, f"doctor_id={ward['other']}", user="doc")
    assert ward["old"] not in seen
    assert seen == set()


def test_an_empty_result_does_not_say_there_are_no_visits(clinic, ward):
    """«مفيش زيارات» على بحث ماطلعش حاجة كدب: الزيارات موجودة، الفلتر هو
    اللي ضيّق."""
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    _seen, html = _ids(clinic, "q=اسم-مش-موجود")
    assert ar["visits"]["no_match"] in html
    assert ar["visits"]["no_visits"] not in html


def test_reset_only_shows_when_something_is_filtered(clinic, ward):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    reset = ar["common"]["reset"]
    _seen, plain = _ids(clinic, "")
    _seen, narrowed = _ids(clinic, "q=ياسين")
    assert reset not in plain.split("data-visit-filters")[1].split("</form>")[0]
    assert reset in narrowed.split("data-visit-filters")[1].split("</form>")[0]


def test_the_next_page_keeps_the_filters(clinic, ward):
    """**الشريط تحت بيشيل الفلاتر معاه** — وإلا «التالي» بيرجّعك لكل
    الزيارات من غير ما تاخد بالك."""
    from app.models import Visit

    from app.utils.paging import PER_PAGE_CHOICES

    # صفحة ونص من أصغر مقاس الشاشة بتعرضه — مش رقم مكتوب هنا، لأن مقاس
    # مش في القايمة بيرجع للافتراضي والاختبار بيقيس صفحة واحدة.
    size = min(PER_PAGE_CHOICES)
    with clinic["app"].app_context():
        for i in range(size):
            clinic["db"].session.add(Visit(
                patient_id=ward["kid"], doctor_id=ward["doc"],
                visit_date=ward["today"] - timedelta(days=i % 30)))
        clinic["db"].session.commit()

    _seen, html = _ids(clinic, f"q=ياسين&per_page={size}")
    assert "page=2" in html
    nxt = [chunk for chunk in html.split('href="') if chunk.startswith("/visits/?")
           and "page=2" in chunk.split('"')[0]]
    assert nxt, "no link to page 2"
    assert "q=" in nxt[0].split('"')[0]


def test_every_word_is_written_in_both_languages():
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    for key in ("search_ph", "no_match"):
        assert ar["visits"][key].strip(), key
        assert en["visits"][key].strip(), key
