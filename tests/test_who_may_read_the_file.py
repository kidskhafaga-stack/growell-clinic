"""مين يقدر يقرا ملف الطفل — GAHAR `IMT.05`.

> 3. There is a list of authorized individuals with access to the patient's
>    medical record.
> 5. There is a signed confidentiality agreement in each staff member's
>    personal file.

**دليل ٤ كان متحقّق من زمان** (كل طريق ورا صلاحية، و`test_permission_sweep`
بيحرسه) — **ودليل ٣ لأ**: الصلاحيات موجودة ومطبّقة، بس مفيش ورقة بتقول «مين
له حق». والقايمة **محسوبة من نفس أسئلة الطرق**، فمش ممكن تقول حاجة غير اللي
البرنامج بيعمله.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _row(clinic, username):
    from app.utils import record_access

    return next(r for r in record_access.rows()
                if r["user"].username == username)


# ============ القايمة محسوبة ============
def test_a_doctor_reads_the_clinical_record(clinic):
    with clinic["app"].app_context():
        row = _row(clinic, "doc")
        assert row["areas"]["file"] and row["areas"]["clinical"]
        assert row["areas"]["visits"]


def test_the_front_desk_opens_the_file_but_not_the_clinical_record(clinic):
    """الاستقبال بيفتح الملف علشان الحجز — **ومش بيشوف الإكلينيكي**."""
    with clinic["app"].app_context():
        row = _row(clinic, "desk")
        assert row["areas"]["clinical"] is False


def test_the_list_says_exactly_what_the_screen_does(clinic):
    """**دي الحتة كلها**: لكل مستخدم ولكل منطقة، القايمة والطريق بيقولوا
    نفس الإجابة. قايمة مكتوبة بالإيد كانت هتبقى صح يوم ما اتكتبت بس."""
    from app.models import User
    from app.utils import record_access

    with clinic["app"].app_context():
        for user in User.query.filter_by(is_active=True).all():
            areas = record_access.areas_for(user)
            for key, module, cap in record_access.AREAS:
                expected = user.can_open(module) and (
                    cap is None or user.can(cap))
                assert areas[key] == bool(expected), (user.username, key)


def test_changing_a_role_changes_the_list_without_touching_it(clinic):
    """دور بيتعدّل → القايمة بتتغيّر لوحدها. من غير سطر في الكود."""
    from app.models import User
    from app.models.role import Role
    from app.utils import record_access

    with clinic["app"].app_context():
        clinic["db"].session.add(Role(name="scribe", label_ar="كاتب",
                                      modules="patients", capabilities=""))
        scribe = User(username="scribe", full_name="كاتب", role="scribe",
                      is_active=True)
        scribe.set_password("secret")
        clinic["db"].session.add(scribe)
        clinic["db"].session.commit()
        assert record_access.areas_for(scribe)["clinical"] is False

        role = Role.query.filter_by(name="scribe").one()
        role.capabilities = "patient_medical"
        clinic["db"].session.commit()
        assert record_access.areas_for(scribe)["clinical"] is True


def test_a_module_the_clinic_switched_off_is_open_to_nobody(clinic):
    """`can_open` مش `can_access`: الدور مسموحله، بس الموديول مقفول."""
    from app.models import Setting
    from app.utils import record_access

    with clinic["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        clinic["db"].session.commit()
        assert _row(clinic, "doc")["areas"]["labs"] is False


def test_a_closed_account_is_not_on_the_list(clinic):
    """حساب اتقفل مابيقراش حاجة — وظهوره في «مين له حق» كان هيكدب."""
    from app.models import User

    with clinic["app"].app_context():
        User.query.filter_by(username="acct").one().is_active = False
        clinic["db"].session.commit()
        from app.utils import record_access

        assert "acct" not in {r["user"].username for r in record_access.rows()}


def test_a_locked_doctor_is_marked_as_seeing_their_own_visits_only(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        assert _row(clinic, "doc")["own_only"] is True
        Setting.set("doctors_see_own_only", "0")
        clinic["db"].session.commit()
        assert _row(clinic, "doc")["own_only"] is False
        assert _row(clinic, "boss")["own_only"] is False


# ============ إقرار السرّية ============
def test_nobody_is_recorded_as_signed_at_first(clinic):
    """فاضي = **ما اتسجّلش**، مش «ما وقّعش»."""
    from app.utils import record_access

    with clinic["app"].app_context():
        names = {u.username for u in record_access.unsigned()}
        assert {"doc", "boss", "desk"} <= names


def test_recording_a_signature_takes_the_paper_s_date(clinic):
    """الورقة ممكن تكون اتوقّعت يوم التعيين من سنتين."""
    from app.models import User
    from app.utils import record_access

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").one()
        boss = User.query.filter_by(username="boss").one()
        then = date.today() - timedelta(days=700)
        record_access.record_signature(doc, on=then, recorder=boss)
        clinic["db"].session.commit()
        assert doc.confidentiality_signed_on == then
        assert doc.confidentiality_recorded_by == boss.id
        assert "doc" not in {u.username for u in record_access.unsigned()}


def test_a_signature_in_the_future_is_refused(clinic):
    from app.models import User
    from app.utils import record_access

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").one()
        with pytest.raises(ValueError):
            record_access.record_signature(
                doc, on=date.today() + timedelta(days=1))


def test_someone_who_reads_nothing_is_not_asked_to_sign(clinic):
    """الإقرار لـ«كل اللي عنده وصول لبيانات المرضى» — `IMT.05` (ج). حد
    مابيوصلش لأي جزء من الملف مش مطلوب منه."""
    from app.models import User
    from app.models.role import Role
    from app.utils import record_access

    with clinic["app"].app_context():
        clinic["db"].session.add(Role(name="cleaner", label_ar="نظافة",
                                      modules="", capabilities=""))
        u = User(username="cleaner", full_name="نظافة", role="cleaner",
                 is_active=True)
        u.set_password("secret")
        clinic["db"].session.add(u)
        clinic["db"].session.commit()
        assert _row(clinic, "cleaner")["reads_record"] is False
        assert "cleaner" not in {x.username for x in record_access.unsigned()}


# ============ الشاشة ============
def test_the_screen_lists_everyone_with_their_access(clinic):
    html = clinic["sign_in"]("boss").get("/users/access").get_data(as_text=True)
    assert "data-access-list" in html
    doc_line = html.split('data-access-user="%d"' % clinic["ids"]["doctor"])[1]
    doc_line = doc_line.split("</tr>")[0]
    assert 'data-area="clinical" data-can="yes"' in doc_line
    desk_line = html.split('data-access-user="%d"' % clinic["ids"]["desk"])[1]
    desk_line = desk_line.split("</tr>")[0]
    assert 'data-area="clinical" data-can="no"' in desk_line


def test_recording_a_signature_from_the_screen(clinic):
    from app.models import User

    then = (date.today() - timedelta(days=30)).isoformat()
    clinic["sign_in"]("boss").post(
        f"/users/{clinic['ids']['doctor']}/confidentiality", data={"on": then})
    with clinic["app"].app_context():
        doc = clinic["db"].session.get(User, clinic["ids"]["doctor"])
        assert doc.confidentiality_signed_on.isoformat() == then


def test_only_an_admin_sees_the_list(clinic):
    assert clinic["sign_in"]("doc").get("/users/access").status_code in (302, 403)
    assert clinic["sign_in"]("desk").post(
        f"/users/{clinic['ids']['doctor']}/confidentiality",
        data={}).status_code in (302, 403)


def test_the_list_prints_with_a_heading(clinic):
    """المراجِع بيطلب الورقة — والورقة لازم تقول هي إيه، ولمين، وامتى."""
    html = clinic["sign_in"]("boss").get("/users/access").get_data(as_text=True)
    head = html.split('class="print-only"')[1].split("</div>\n</div>")[0]
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    assert ar["access"]["title"] in head
    assert ar["access"]["printed_at"] in head


def test_every_word_is_written_in_both_languages():
    import json

    from app.utils.record_access import AREAS

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    assert set(ar["access"]) == set(en["access"])
    for key in ar["access"]:
        assert ar["access"][key].strip(), key
        assert en["access"][key].strip(), key
    for key, _module, _cap in AREAS:
        assert f"area_{key}" in ar["access"], key
