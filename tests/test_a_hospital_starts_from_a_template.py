"""تجهيز المنشأة — والمستشفى كانت نوع من غير قالب.

**الشاشة كانت اسمها «تجهيز العيادة للتشغيل»** وهي بتخدم مستشفى كمان:
`FACILITY_TYPES` فيها `hospital` من زمان، بتسع قدرات — طوارئ وداخلي
وعناية وعمليات. فالعنوان بقى «تجهيز المنشأة».

**والطريق السريع كان مقفول قدامها.** «ابدأ من قالب جاهز» كان خمسة
كلهم عيادات ومراكز، فمستشفى كانت بتبدأ من صفر وتعلّم قدراتها بإيدها —
وهي **أكتر منشأة محتاجة الطريق السريع**، وأكتر واحدة الغلط فيها بيوقع
موديولز كاملة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402


def test_the_screen_is_not_called_the_clinic_any_more():
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert "العيادة" not in ar["wizard"]["title"]
    assert "المنشأة" in ar["wizard"]["title"]
    assert "clinic" not in en["wizard"]["title"].lower()


def test_a_hospital_can_start_from_a_template():
    from app.utils import facility

    assert "hospital" in facility.TEMPLATES
    assert facility.TEMPLATES["hospital"]["type"] == "hospital"


def test_the_template_turns_on_what_a_hospital_has(clinic):
    """والقدرات دي هي اللي ويزارد الأقسام بيسأل عنها بعد كده — فمستشفى
    بدأت من القالب بتلاقي خانات الطوارئ والعناية والحضّانات مستنياها."""
    from app.utils import facility
    from app.utils import ward_plan

    caps = facility.TEMPLATES["hospital"]["caps"]
    for needed in ("emergency_care", "ward", "icu", "nicu", "surgery"):
        assert needed in caps

    asked = [plan["cap"] for plan in ward_plan.plans_for(caps)]
    assert asked == ["emergency_care", "icu", "nicu", "ward", "surgery"]


def test_the_template_matches_the_type_it_names():
    """قالب بيقول «مستشفى» وبيعلّم قدرات أقل من نوع المستشفى بيخلّي
    اللي اختاره يفتكر إنه خلص وهو ناقص."""
    from app.utils import facility

    template = set(facility.TEMPLATES["hospital"]["caps"])
    kind = set(facility.FACILITY_TYPES["hospital"]["caps"])

    assert kind <= template


def test_every_template_has_a_name_in_both_languages():
    """**حارس على القايمة كلها مش على الجديد بس** — القالب الجاي محتاج
    نفس الحاجة، والزرار من غير اسم بيطلع مفتاح خام على الشاشة."""
    import json

    from app.utils import facility

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    for key in facility.TEMPLATES:
        assert (ar["templates"].get(key) or "").strip(), key
        assert (en["templates"].get(key) or "").strip(), key


def test_every_template_points_at_a_real_type_and_real_capabilities():
    from app.utils import facility

    for key, meta in facility.TEMPLATES.items():
        assert meta["type"] in facility.FACILITY_TYPES, key
        for cap in meta["caps"]:
            assert cap in facility.CAPABILITY_MODULES, (key, cap)


def test_the_hospital_template_is_offered_on_the_screen(clinic):
    """**والشاشة دي للمالك بس** — مش لأي أدمن.

    `owner_required` مكتوب سببه في `utils/decorators`: *"the
    institution/clinic-level settings a plain admin must not reshape"*.
    ونوع المنشأة بيقفل ويفتح موديولز للبرنامج كله، فده مكانه الصح.
    """
    import json

    from app.models import User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        boss.is_super_admin = True
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get(
        "/settings/setup").get_data(as_text=True)

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    assert ar["templates"]["hospital"] in page
    assert ar["wizard"]["title"] in page


def test_a_plain_admin_cannot_reshape_the_facility(clinic):
    """أدمن عادي بيدير العيادة؛ اللي بيغيّر شكل المنشأة نفسها هو المالك."""
    assert clinic["sign_in"]("boss").get(
        "/settings/setup").status_code == 403
