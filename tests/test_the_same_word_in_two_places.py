"""الاختصارات الموحّدة — GAHAR `IMT.04`.

**نفس الاختصار مقبول في ملاحظة وممنوع في موافقة.** (د) بيقول بالنص إن
فيه مواقف ممنوع فيها **حتى المسموح** — الموافقة المستنيرة، وأي ورقة
الأهل بياخدوها. فالفاحص بياخد **سياق** مش نص بس.

**والمطابقة هي كل الشغل.** «MS» اختصار ممنوع، و«ms» جوّه كلمة مش هو،
و«U» لوحدها غير الـ«U» اللي في «BUN». والعربي مالوش `\\b` في بايثون زي
الإنجليزي، فالحدود مكتوبة بإيد — والملف ده بيثبّت إنها بتشتغل في
اللغتين.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_with_rules(clinic):
    """عيادة كتبت قايمتيها."""
    from app.models import Abbreviation

    with clinic["app"].app_context():
        clinic["db"].session.add_all([
            Abbreviation(text="U", kind="banned", means="units"),
            Abbreviation(text="QD", kind="banned", means="يومياً"),
            Abbreviation(text="ق.ي", kind="banned", means="قبل الأكل"),
            Abbreviation(text="MS", kind="banned", means="morphine sulfate"),
            Abbreviation(text="IV", kind="approved", means="وريد"),
            Abbreviation(text="مج", kind="approved", means="مليجرام"),
        ])
        clinic["db"].session.commit()
    return clinic


# ============ القايمة بتبدأ فاضية ============
def test_the_program_ships_no_abbreviations(clinic):
    """(ب) بيشاور على مرجع **بره الكتاب** — ورقم `CSS.05` كان جوّاه."""
    from app.utils import abbreviations as ab

    from app.models import Abbreviation

    with clinic["app"].app_context():
        assert Abbreviation.query.count() == 0
        assert ab.find("أدي 10 U وريد") == []
        assert ab.violations() == []


# ============ السياق: نفس الاختصار، حُكمين ============
def test_an_approved_abbreviation_passes_in_a_note(clinic_with_rules):
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert ab.find("أدي الجرعة IV", context="note") == []
        assert ab.clean("أدي الجرعة IV", context="note")


def test_but_the_same_one_fails_on_a_consent(clinic_with_rules):
    """**دي الحتة كلها** — (د) بالنص: *even the approved list*."""
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        found = ab.find("أدي الجرعة IV", context="family")
        assert [f["text"] for f in found] == ["IV"]
        assert found[0]["kind"] == "approved"


def test_a_banned_one_fails_everywhere(clinic_with_rules):
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        for context in ("note", "family"):
            found = ab.find("أدي 10 U", context=context)
            assert [f["text"] for f in found] == ["U"]


def test_the_message_says_what_to_write_instead(clinic_with_rules):
    """«اكتب units» أحسن من «فيه اختصار ممنوع»."""
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert ab.find("10 U")[0]["means"] == "units"


def test_a_context_the_checker_does_not_know_is_refused(clinic_with_rules):
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        with pytest.raises(ValueError):
            ab.find("حاجة", context="billboard")


# ============ المطابقة ============
def test_an_abbreviation_inside_a_longer_word_is_not_it(clinic_with_rules):
    """«U» جوّه «BUN» مش الاختصار — والفحص اللي بيمسكها بيطلّع ضوضاء
    ومحدّش بيفتحه تاني."""
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert ab.find("BUN مرتفع") == []
        assert ab.find("QUADRANT") == []


def test_case_matters(clinic_with_rules):
    """«MS» اختصار، و«ms» مللي ثانية أو جزء من كلمة."""
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert [f["text"] for f in ab.find("أدي MS")] == ["MS"]
        assert ab.find("القراية 20 ms") == []


def test_an_arabic_abbreviation_inside_an_arabic_word_is_not_it(
        clinic_with_rules):
    """**والعربي مالوش `\\b` في بايثون.**

    فلو الحدود اتسابت للتعبير العادي، «ق.ي» كانت هتتمسك جوّه كلام عربي
    أطول — والقايمة تمتلي بمخالفات مش موجودة.
    """
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert [f["text"] for f in ab.find("ياخد ق.ي بيوم")] == ["ق.ي"]
        # جوّه كلمة أطول — مش هو.
        assert ab.find("الوقاية") == []
        assert ab.find("شقيقي") == []


def test_a_number_stuck_to_it_is_the_whole_point(clinic_with_rules):
    """**«10U» هي الحالة اللي القوايم دي موجودة علشانها** — بتتقرا «100».

    أول نسخة من التعبير كانت بتلغي الاختصار لو قبله رقم، يعني كانت
    بتفوّت أخطر شكل فيه. والتعليق اللي كتبته كان بيقول العكس — الكود
    هو اللي كان غلط مش التعليق.
    """
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        assert [f["text"] for f in ab.find("أدي 10U وريد")] == ["U"]
        assert [f["text"] for f in ab.find("أدي ١٠U وريد")] == ["U"]
        # ورقم **بعده** بيلغيه: «U2» رمز حاجة تانية مش جرعة.
        assert ab.find("U2 concert") == []


def test_empty_text_is_not_a_violation(clinic_with_rules):
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        for empty in (None, "", "   ", "\n"):
            assert ab.find(empty) == []


def test_an_inactive_rule_stops_applying(clinic_with_rules):
    """إيقاف بدل مسح — التاريخ يفضل مقروء واللي بكرة يبقى نضيف."""
    from app.models import Abbreviation
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        row = Abbreviation.query.filter_by(text="QD").one()
        row.is_active = False
        clinic_with_rules["db"].session.commit()

        assert ab.find("QD") == []
        # لسه في القايمة على الشاشة، بس مش بتتطبّق.
        assert Abbreviation.query.filter_by(text="QD").one().is_active is False


# ============ الرصد — دليل ٤ ============
def _visit_with(clinic, **fields):
    from app.models import Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        row = Visit(patient_id=clinic["ids"]["child"],
                    visit_date=local_today(), doctor_id=clinic["ids"]["doctor"],
                    **fields)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def test_a_banned_abbreviation_in_a_note_is_monitored(clinic_with_rules):
    """*"Violation of the list of not-to-use symbols/abbreviations is
    **monitored**"* — دليل ٤."""
    from app.utils import abbreviations as ab

    vid = _visit_with(clinic_with_rules, plan="أدي 10 U وريد")

    with clinic_with_rules["app"].app_context():
        found = ab.violations()
        assert len(found) == 1
        assert found[0]["model"] == "Visit"
        assert found[0]["field"] == "plan"
        assert found[0]["row"].id == vid
        assert [f["text"] for f in found[0]["found"]] == ["U"]


def test_an_approved_one_in_a_note_is_not(clinic_with_rules):
    from app.utils import abbreviations as ab

    _visit_with(clinic_with_rules, plan="أدي الجرعة IV")

    with clinic_with_rules["app"].app_context():
        assert ab.violations() == []


def test_an_approved_one_on_a_family_document_is(clinic_with_rules):
    """**(د)** — الورق اللي بيروح للأهل بقاعدة أصرم."""
    from app.models import Consent
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        clinic_with_rules["db"].session.add(Consent(
            patient_id=clinic_with_rules["ids"]["child"],
            guardian_name="ولي الأمر",
            statement="بوافق على إعطاء الدوا IV"))
        clinic_with_rules["db"].session.commit()

        found = ab.violations()
        assert [f["model"] for f in found] == ["Consent"]
        assert found[0]["context"] == "family"
        assert [f["text"] for f in found[0]["found"]] == ["IV"]


def test_the_scanned_fields_are_named_not_everything(clinic_with_rules):
    """فحص بيشمل كل حقل نص في البرنامج بيطلّع ضوضاء ومحدّش بيفتحه."""
    from app.utils import abbreviations as ab

    assert set(ab.SCANNED) == {"Prescription", "Visit", "RoundNote",
                               "DischargeSummary", "Consent"}
    for name, (context, fields) in ab.SCANNED.items():
        assert context in ("note", "family"), name
        assert fields, name


def test_a_field_outside_the_list_is_not_scanned(clinic_with_rules):
    """`Visit.referral_note` مش في القايمة — فما بيتفحصش، وده مقصود
    ومكتوب مش سهو."""
    from app.utils import abbreviations as ab

    _visit_with(clinic_with_rules, referral_note="أدي 10 U")

    with clinic_with_rules["app"].app_context():
        assert "referral_note" not in ab.SCANNED["Visit"][1]
        assert ab.violations() == []


def test_the_counts_feed_a_screen(clinic_with_rules):
    from app.utils import abbreviations as ab

    _visit_with(clinic_with_rules, plan="أدي 10 U")

    with clinic_with_rules["app"].app_context():
        got = ab.counts()
        assert got["violations"] == 1
        assert got["banned"] == 4
        assert got["approved"] == 2


def test_nothing_is_monitored_before_the_clinic_writes_its_list(clinic):
    """ساكت لحد ما المكان يقول رأيه — زي كل رقم وسياسة تانية هنا."""
    from app.utils import abbreviations as ab

    _visit_with(clinic, plan="أدي 10 U QD ق.ي MS")

    with clinic["app"].app_context():
        assert ab.violations() == []
        assert ab.counts()["violations"] == 0


# ================================================ الباب ====
def test_settings_has_a_door_and_it_says_the_list_is_empty(clinic):
    """ساكت بس **مش مخفي** — والشاشة بتقول ليه القايمة فاضية."""
    page = clinic["sign_in"]("boss").get(
        "/settings/abbreviations").get_data(as_text=True)

    assert "data-abbrev-list" in page
    assert "data-abbrev-empty" in page


def test_the_clinic_can_write_a_rule(clinic):
    from app.models import Abbreviation

    client = clinic["sign_in"]("boss")
    client.post("/settings/abbreviations", follow_redirects=True, data={
        "action": "add", "text": "QD", "kind": "banned", "means": "يومياً"})

    with clinic["app"].app_context():
        row = Abbreviation.query.filter_by(text="QD").one()
        assert row.kind == "banned"
        assert row.means == "يومياً"
        assert row.is_active


def test_the_same_symbol_twice_is_refused(clinic):
    """حُكمين على حاجة واحدة بيتعارضوا."""
    from app.models import Abbreviation

    client = clinic["sign_in"]("boss")
    for kind in ("banned", "approved"):
        client.post("/settings/abbreviations", follow_redirects=True, data={
            "action": "add", "text": "IV", "kind": kind})

    with clinic["app"].app_context():
        rows = Abbreviation.query.filter_by(text="IV").all()
        assert len(rows) == 1
        assert rows[0].kind == "banned"


def test_a_rule_with_no_symbol_or_no_ruling_is_refused(clinic):
    from app.models import Abbreviation

    client = clinic["sign_in"]("boss")
    client.post("/settings/abbreviations", follow_redirects=True,
                data={"action": "add", "text": "  ", "kind": "banned"})
    client.post("/settings/abbreviations", follow_redirects=True,
                data={"action": "add", "text": "ZZ", "kind": "whatever"})

    with clinic["app"].app_context():
        assert Abbreviation.query.count() == 0


def test_switching_one_off_keeps_it_on_the_screen(clinic_with_rules):
    """**إيقاف مش مسح** — التاريخ يفضل مقروء والمخالفات القديمة مفهومة."""
    from app.models import Abbreviation
    from app.utils import abbreviations as ab

    with clinic_with_rules["app"].app_context():
        rid = Abbreviation.query.filter_by(text="QD").one().id

    client = clinic_with_rules["sign_in"]("boss")
    client.post("/settings/abbreviations", follow_redirects=True,
                data={"action": "toggle", "id": rid})

    page = client.get("/settings/abbreviations").get_data(as_text=True)
    assert f'data-abbrev="{rid}"' in page

    with clinic_with_rules["app"].app_context():
        assert ab.find("QD") == []


def test_the_screen_shows_the_violations_it_found(clinic_with_rules):
    vid = _visit_with(clinic_with_rules, plan="أدي 10 U")

    page = clinic_with_rules["sign_in"]("boss").get(
        "/settings/abbreviations").get_data(as_text=True)

    assert f'data-violation="Visit-{vid}-plan"' in page
    assert 'data-hit="U"' in page
    assert "units" in page


def test_the_screen_marks_the_stricter_family_rule(clinic_with_rules):
    """(د) — والشاشة بتقول ليه المسموح بقى مخالفة هنا."""
    from app.models import Consent

    with clinic_with_rules["app"].app_context():
        clinic_with_rules["db"].session.add(Consent(
            patient_id=clinic_with_rules["ids"]["child"],
            guardian_name="ولي الأمر", statement="موافق على الدوا IV"))
        clinic_with_rules["db"].session.commit()

    page = clinic_with_rules["sign_in"]("boss").get(
        "/settings/abbreviations").get_data(as_text=True)

    assert 'data-context="family"' in page
    assert 'data-hit="IV"' in page


def test_a_clean_clinic_is_told_so(clinic_with_rules):
    page = clinic_with_rules["sign_in"]("boss").get(
        "/settings/abbreviations").get_data(as_text=True)

    assert "data-abbrev-violations" in page
    assert "data-violation=" not in page


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    from app.i18n import _load_translations, _lookup
    from app.models import ABBREV_KINDS
    from app.utils import abbreviations as ab

    tables = _load_translations()
    keys = [("abbrev", f"kind_{k}") for k in ABBREV_KINDS]
    keys += [("abbrev", f"m_{name}") for name in ab.SCANNED]
    keys += [("abbrev", k) for k in (
        "title", "sub", "violations", "violations_hint", "none_found",
        "no_list", "where", "field", "found", "family_rule", "text",
        "kind", "means", "note", "off", "on", "saved", "not_saved",
        "already_there", "scanned_here")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"
