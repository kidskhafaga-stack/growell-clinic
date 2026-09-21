"""قايمة العيادة اللي حد يقدر يمسح منها حاجة مستعملة.

`utils/lookups` بيقول القاعدة في دوكسترينجه: *"A built-in cannot be
deleted, and **neither can one in use** — deleting it would leave items
pointing at something that no longer exists, which is a report that
**quietly drops rows** rather than an error somebody sees."*

**والحارس ده اتكتب لأني وقعت فيه.** `usage_counts` فيها سلسلة `elif`
بدومين واحد لكل واحدة، وآخرها `else: 0`. فأول ما ضفت قايمة الأنظمة
الغذائية (`ICD.13`) من غير فرع ليها، كل نظام غذائي بقى بيبان **مش
مستعمل** — يعني يتمسح وكل أمر أكل بيشاور عليه يبقى شاور على حاجة
مش موجودة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def test_every_list_knows_how_to_count_what_uses_it(clinic):
    """أي دومين في `DOMAINS` لازم يكون ليه فرع حقيقي في `usage_counts`.

    الفحص بيتعمل بالسلوك مش بقراية الكود: بنحط صف في كل قايمة، وبنشوف
    إن `usage_counts` بترجّعه — واللي مالوش فرع بيرجّع صفر دايماً،
    وده اللي بنمنعه.
    """
    import inspect

    from app.utils import lookups

    source = inspect.getsource(lookups.usage_counts)
    missing = [d for d in lookups.DOMAINS if f'"{d}"' not in source]

    assert not missing, (
        "قوايم مالهاش فرع في usage_counts، فأي صف فيها بيبان «مش "
        "مستعمل» ويتمسح ومعاه كل اللي بيشاور عليه: " + ", ".join(missing))


def test_a_diet_in_use_cannot_be_deleted(clinic):
    """**الحالة اللي الحارس اتكتب علشانها.**"""
    from app.models import Lookup, Patient
    from app.utils import lookups, nutrition

    with clinic["app"].app_context():
        clinic["db"].session.add(Lookup(
            domain="special_diet", key="d1", name_ar="حمية سكري",
            name_en="Diabetic"))
        clinic["db"].session.commit()

        row = Lookup.query.filter_by(domain="special_diet", key="d1").one()
        counts = lookups.usage_counts("special_diet")
        assert counts["d1"] == 0
        assert lookups.can_delete(row, counts)[0] is True

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        nutrition.order(patient, "d1")
        clinic["db"].session.commit()

        counts = lookups.usage_counts("special_diet")
        assert counts["d1"] == 1
        assert lookups.can_delete(row, counts)[0] is False


def test_an_unused_diet_can_still_be_removed(clinic):
    """القاعدة مش «ما تمسحش خالص» — «ما تمسحش المستعمل»."""
    from app.models import Lookup
    from app.utils import lookups

    with clinic["app"].app_context():
        clinic["db"].session.add(Lookup(
            domain="special_diet", key="d9", name_ar="نظام ما اتستعملش",
            name_en="Unused"))
        clinic["db"].session.commit()

        row = Lookup.query.filter_by(domain="special_diet", key="d9").one()
        assert lookups.can_delete(row, lookups.usage_counts(
            "special_diet"))[0] is True
