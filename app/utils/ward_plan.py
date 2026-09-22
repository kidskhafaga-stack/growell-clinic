"""بناء الأقسام بضغطة — والأسئلة بتيجي من اللي المنشأة علّمته.

**السؤال اللي البرنامج كان بيسأله غلط.** شاشة التجهيز بتقول «أضف قسم»
وبعدين «أضف حيّز» وبعدين «أضف سرير»، تلات مرات في تلات مستويات، لكل
سرير في المستشفى. ومستشفى صغيّرة فيها تلاتين سرير يعني تلاتين دورة.

والسؤال اللي المستشفى بتجاوبه بسهولة هو: **«الطوارئ فيها كام بارتشن؟»**
و**«العناية فيها كام سرير، ومنهم كام عزل؟»** و**«الحضّانة فيها كام
حضّانة وكام سرير؟»**. فده اللي الملف ده بيسأله، وبيترجمه لصفوف.

---

**والأسئلة مش واحدة لكل منشأة.** `settings/setup` بيخزّن قدرات المنشأة،
فعيادة ماعلّمتش «عناية» ما تتسألش عن بارتشنات العناية — نفس مبدأ
التبويبات في ملف الطفل: **حاجة عمرها ما هتحصل مش بتاخد مكان على
الشاشة**.

**والقسم الموجود بيتزوّد عليه مش بيتكرّر.** «طوارئ» مرتين هي بالظبط
اللغبطة اللي الشاشة دي موجودة علشانها.
"""
from app.extensions import db
from app.models.place import Bed, Space, Unit

#: القدرة → إيه اللي بتبنيه. الترتيب هو ترتيب الظهور على الشاشة.
#:
#: كل خطة بتقول: نوع القسم، والأسئلة، وكل إجابة بتعمل إيه. و«كام سرير
#: في الغرفة» سؤال لوحده في الداخلي بس، لأن ده المكان الوحيد اللي
#: الغرفة فيه بتشيل أكتر من سرير كقاعدة.
PLANS = [
    {
        "cap": "emergency_care",
        "unit_kind": "emergency",
        # بارتشن بسرير واحد — والتعليق في `utils/beds` بيقول ليه:
        # «one bed per partition, which is what makes crowding countable
        # as every partition occupied».
        "questions": [
            {"key": "partitions", "space_kind": "partition",
             "bed_kind": "trolley", "beds_each": 1},
        ],
    },
    {
        "cap": "icu",
        "unit_kind": "icu",
        "questions": [
            {"key": "beds", "space_kind": "bay", "bed_kind": "bed",
             "one_space": True},
            # **العزل حيّز مش سرير.** اللي بيعزل الطفل هو الحيطة اللي
            # حواليه، مش هيكل السرير — والتعليق ده مكتوب في الموديل
            # نفسه، فبارتشن العزل بيتعمل واحد لكل سرير عزل.
            {"key": "isolation", "space_kind": "partition",
             "bed_kind": "bed", "beds_each": 1, "isolation": True},
        ],
    },
    {
        "cap": "nicu",
        "unit_kind": "nicu",
        # صالة واحدة بتشيل التلات أنواع — وده السبب اللي خلّى النوع
        # يبقى على السرير مش على القسم.
        "questions": [
            {"key": "incubators", "space_kind": "bay", "bed_kind": "incubator",
             "one_space": True},
            {"key": "cots", "space_kind": "bay", "bed_kind": "cot",
             "one_space": True},
            {"key": "capsules", "space_kind": "bay", "bed_kind": "capsule",
             "one_space": True},
        ],
    },
    {
        "cap": "ward",
        "unit_kind": "ward",
        "questions": [
            {"key": "rooms", "space_kind": "room", "bed_kind": "bed",
             "beds_each_key": "beds_per_room", "beds_each": 1},
        ],
    },
    {
        "cap": "day_care",
        "unit_kind": "day_care",
        "questions": [
            {"key": "beds", "space_kind": "bay", "bed_kind": "bed",
             "one_space": True},
        ],
    },
    {
        "cap": "surgery",
        "unit_kind": "recovery",
        "questions": [
            {"key": "beds", "space_kind": "bay", "bed_kind": "bed",
             "one_space": True},
        ],
    },
]

#: أعلى رقم مقبول في أي خانة. مش سياسة، **حارس غلطة كتابة**: حد كتب
#: ٦٠٠ بدل ٦ بيعمل ستمية سرير محدّش يقدر يشيلهم بسهولة.
MAX_EACH = 200


def plans_for(caps):
    """الخطط اللي المنشأة دي بتتسأل عنها — **بترتيب `PLANS`**."""
    have = set(caps or ())
    return [plan for plan in PLANS if plan["cap"] in have]


def _unit_for(kind, name):
    """القسم الموجود من النوع ده، أو واحد جديد. **مش بيكرّر.**"""
    row = (Unit.query.filter_by(kind=kind)
           .order_by(Unit.id).first())
    if row is not None:
        return row, False
    from app.utils import bed_billing

    row = Unit(name=name, kind=kind,
               billing_basis=bed_billing.default_basis(kind),
               sort_order=Unit.query.count())
    db.session.add(row)
    db.session.flush()
    return row, True


def _spaces_of(unit):
    """**بالسؤال مش بالعلاقة.**

    `unit.spaces` بتتحمّل مرة، والصف اللي اتعمل بـ`unit_id` و`flush`
    في نفس المعاملة ما بيدخلش القايمة المحمّلة — فالسؤال التاني كان
    بيلاقيها فاضية ويعمل صالة تانية وتالتة.
    """
    return Space.query.filter_by(unit_id=unit.id).count()


def _beds_of(space):
    return Bed.query.filter_by(space_id=space.id).count()


def _space_for(unit, kind, name, isolation=False):
    row = (Space.query
           .filter_by(unit_id=unit.id, kind=kind, is_isolation=bool(isolation))
           .order_by(Space.id).first())
    if row is not None:
        return row
    row = Space(unit_id=unit.id, name=name, kind=kind,
                is_isolation=bool(isolation), sort_order=_spaces_of(unit))
    db.session.add(row)
    db.session.flush()
    return row


def preview(caps, answers, names=None):
    """إيه اللي هيتعمل — **من غير ما يتعمل**.

    الشاشة بتقوله قبل الضغط، لأن ضغطة واحدة بتعمل تلاتين صف والرجوع
    فيها مش زي الرجوع في صف واحد.
    """
    out = []
    for plan in plans_for(caps):
        for question in plan["questions"]:
            count = _count(answers, plan["cap"], question["key"])
            if not count:
                continue
            each = _beds_each(answers, plan["cap"], question)
            out.append({
                "cap": plan["cap"], "unit_kind": plan["unit_kind"],
                "key": question["key"], "spaces": 1 if question.get(
                    "one_space") else count,
                "beds": count if question.get("one_space") else count * each,
                "bed_kind": question["bed_kind"],
                "isolation": bool(question.get("isolation")),
            })
    return out


def field(cap, key):
    """اسم الخانة على الشاشة.

    **مسمّى بالقسم عن قصد.** «كام سرير» سؤال في العناية وفي الرعاية
    النهارية وفي الإفاقة — وتلاتتهم لو اتسمّوا `beds`، الفورم بتبعت
    واحدة والتانيتين بيضيعوا من غير ما حد ياخد باله.
    """
    return f"{cap}__{key}"


def _count(answers, cap, key):
    try:
        value = int(answers.get(field(cap, key)) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(value, MAX_EACH))


def _beds_each(answers, cap, question):
    if question.get("beds_each_key"):
        return _count(answers, cap, question["beds_each_key"]) or question.get(
            "beds_each", 1)
    return question.get("beds_each", 1)


def build(caps, answers, names):
    """ينفّذ الخطة. المتصل بيعمل commit.

    ``names`` بتجيب اسم كل قسم وحيّز بلغة العيادة — البرنامج ما بيخترعش
    أسامي عربية في الكود.
    """
    made = {"units": 0, "spaces": 0, "beds": 0}
    for plan in plans_for(caps):
        rows = [q for q in plan["questions"]
                if _count(answers, plan["cap"], q["key"])]
        if not rows:
            continue
        unit, fresh = _unit_for(plan["unit_kind"],
                                names(f"unit.{plan['unit_kind']}"))
        made["units"] += 1 if fresh else 0
        for question in rows:
            count = _count(answers, plan["cap"], question["key"])
            each = _beds_each(answers, plan["cap"], question)
            if question.get("one_space"):
                before = _beds_of(space := _space_for(
                    unit, question["space_kind"],
                    names(f"space.{question['space_kind']}")))
                made["spaces"] += 1 if not before else 0
                made["beds"] += _fill(space, question["bed_kind"], count,
                                      names)
            else:
                for _ in range(count):
                    seen = _spaces_of(unit)
                    space = Space(
                        unit_id=unit.id, kind=question["space_kind"],
                        is_isolation=bool(question.get("isolation")),
                        name=names(f"space.{question['space_kind']}",
                                   seen + 1),
                        sort_order=seen)
                    db.session.add(space)
                    db.session.flush()
                    made["spaces"] += 1
                    made["beds"] += _fill(space, question["bed_kind"], each,
                                          names)
    return made


def _fill(space, bed_kind, count, names):
    start = _beds_of(space)
    for i in range(count):
        db.session.add(Bed(space_id=space.id, kind=bed_kind,
                           name=names(f"bed.{bed_kind}", start + i + 1),
                           sort_order=start + i))
    db.session.flush()
    return count


# --- الحذف: اللي ماتستعملش يتمسح، واللي اتستعمل يتوقف ------------------
#
# **الريبو ده عمره ما بيمسح تاريخ إكلينيكي.** سرير نام فيه طفل لو اتمسح،
# صفوف `BedStay` تفضل بتشاور على حاجة مش موجودة — وده «تقرير بيسقّط
# صفوف في الضلمة» زي ما دوكسترينج `utils/lookups` بيسمّيه.
#
# فالقاعدة سطرين: **اللي عمره ما اتستعمل يتمسح، واللي اتستعمل يتوقف** —
# و«أخرجه من الخدمة» موجود من الأول. واللي بيمنع الحذف بيتقال **باسمه**،
# مش «مش ينفع».


class InUse(Exception):
    """السبب اللي منع الحذف — بيتحوّل لرسالة على الشاشة."""


def bed_used(bed):
    """السرير ده نام فيه طفل قبل كده — **ولو مرة واحدة من سنة**."""
    from app.models import BedStay

    return db.session.query(
        BedStay.query.filter(BedStay.bed_id == bed.id).exists()).scalar()


def delete_bed(bed):
    """المتصل بيعمل commit."""
    if bed is None:
        raise ValueError("no bed")
    if bed_used(bed):
        raise InUse("bed_used")
    db.session.delete(bed)


def delete_space(space):
    """الحيّز وأسرّته — **لو ولا سرير فيهم اتستعمل**.

    الكل أو لا حاجة عن قصد: مسح النص بيسيب غرفة فيها سرير واحد ومحدّش
    فاهم ليه.
    """
    if space is None:
        raise ValueError("no space")
    used = [bed for bed in space.beds if bed_used(bed)]
    if used:
        raise InUse("space_has_used_beds")
    for bed in list(space.beds):
        db.session.delete(bed)
    db.session.delete(space)


def delete_unit(unit):
    """القسم وكل اللي تحته — بنفس الشرط."""
    if unit is None:
        raise ValueError("no unit")
    for space in unit.spaces:
        if any(bed_used(bed) for bed in space.beds):
            raise InUse("unit_has_used_beds")
    for space in list(unit.spaces):
        for bed in list(space.beds):
            db.session.delete(bed)
        db.session.delete(space)
    db.session.delete(unit)


def space_deletable(space):
    """نفس قاعدة القسم، مستوى تحت."""
    if space is None:
        return False
    return not any(bed_used(bed) for bed in space.beds)


def deletable(unit):
    """يتمسح ولا لأ — **والشاشة بتسأل ده قبل ما ترسم الزرار**.

    زرار بيرفض كل مرة تضغطه أسوأ من زرار مش موجود: بيعلّم اللي قدام
    الشاشة إن الأزرار بتكدب.
    """
    if unit is None:
        return False
    return not any(bed_used(bed) for space in unit.spaces
                   for bed in space.beds)
