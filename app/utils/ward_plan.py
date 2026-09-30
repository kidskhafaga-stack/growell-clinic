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


def _unit_for(kind, name, name_en=None):
    """القسم الموجود من النوع ده، أو واحد جديد. **مش بيكرّر.**"""
    row = (Unit.query.filter_by(kind=kind)
           .order_by(Unit.id).first())
    if row is not None:
        return row, False
    from app.utils import bed_billing

    row = Unit(name=name, name_en=name_en, kind=kind,
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


def _space_for(unit, kind, name, isolation=False, name_en=None):
    row = (Space.query
           .filter_by(unit_id=unit.id, kind=kind, is_isolation=bool(isolation))
           .order_by(Space.id).first())
    if row is not None:
        return row
    row = Space(unit_id=unit.id, name=name, name_en=name_en, kind=kind,
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


def build(caps, answers, names, names_en=None):
    """ينفّذ الخطة. المتصل بيعمل commit.

    ``names`` بتجيب اسم كل قسم وحيّز بلغة العيادة — البرنامج ما بيخترعش
    أسامي عربية في الكود. و``names_en`` نفس الأسامي بالإنجليزي، علشان
    الشاشة الإنجليزي ما تعرضش عربي («ليه العربي فى الشاشة الانجليزي»).
    """
    def english(key, number=None):
        return names_en(key, number) if names_en else None

    made = {"units": 0, "spaces": 0, "beds": 0}
    for plan in plans_for(caps):
        rows = [q for q in plan["questions"]
                if _count(answers, plan["cap"], q["key"])]
        if not rows:
            continue
        unit, fresh = _unit_for(plan["unit_kind"],
                                names(f"unit.{plan['unit_kind']}"),
                                english(f"unit.{plan['unit_kind']}"))
        made["units"] += 1 if fresh else 0
        for question in rows:
            count = _count(answers, plan["cap"], question["key"])
            each = _beds_each(answers, plan["cap"], question)
            if question.get("one_space"):
                before = _beds_of(space := _space_for(
                    unit, question["space_kind"],
                    names(f"space.{question['space_kind']}"),
                    name_en=english(f"space.{question['space_kind']}")))
                made["spaces"] += 1 if not before else 0
                made["beds"] += _fill(space, question["bed_kind"], count,
                                      names, english)
            else:
                for _ in range(count):
                    seen = _spaces_of(unit)
                    space = Space(
                        unit_id=unit.id, kind=question["space_kind"],
                        is_isolation=bool(question.get("isolation")),
                        name=names(f"space.{question['space_kind']}",
                                   seen + 1),
                        name_en=english(f"space.{question['space_kind']}",
                                        seen + 1),
                        sort_order=seen)
                    db.session.add(space)
                    db.session.flush()
                    made["spaces"] += 1
                    made["beds"] += _fill(space, question["bed_kind"], each,
                                          names, english)
    return made


def _fill(space, bed_kind, count, names, english=None):
    start = _beds_of(space)
    for i in range(count):
        db.session.add(Bed(space_id=space.id, kind=bed_kind,
                           name=names(f"bed.{bed_kind}", start + i + 1),
                           name_en=(english(f"bed.{bed_kind}", start + i + 1)
                                    if english else None),
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


def used_bed_ids():
    """كل سرير نام فيه طفل قبل كده — **استعلام واحد للمستشفى كلها**.

    شاشة التجهيز بتسأل «يتمسح؟» عن كل سرير وحيّز وقسم قبل ما ترسم زرار
    المسح. سؤال لكل سرير كان بيخلّي الشاشة تكبر مع المستشفى: عشرين سرير
    زيادة كانوا تلاتين استعلام زيادة. فالشاشة بتاخد الإجابة مرة، والمسح
    نفسه (:func:`delete_bed`) بيسأل من جديد — لأنه الفعل، والشاشة
    اترسمت من ثواني.
    """
    from app.models import BedStay

    return {row[0] for row in
            db.session.query(BedStay.bed_id).distinct().all()}


def bed_used(bed, used=None):
    """السرير ده نام فيه طفل قبل كده — **ولو مرة واحدة من سنة**.

    ``used`` هو :func:`used_bed_ids` لو الشاشة جابته مرة؛ من غيره السؤال
    بيتسأل على السرير ده بس.
    """
    if used is not None:
        return bed.id in used
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


def space_deletable(space, used=None):
    """نفس قاعدة القسم، مستوى تحت."""
    if space is None:
        return False
    return not any(bed_used(bed, used) for bed in space.beds)


def deletable(unit, used=None):
    """يتمسح ولا لأ — **والشاشة بتسأل ده قبل ما ترسم الزرار**.

    زرار بيرفض كل مرة تضغطه أسوأ من زرار مش موجود: بيعلّم اللي قدام
    الشاشة إن الأزرار بتكدب.
    """
    if unit is None:
        return False
    return not any(bed_used(bed, used) for space in unit.spaces
                   for bed in space.beds)


# --- الأسامي بالإنجليزي -------------------------------------------------
#
# «ليه العربي فى الشاشة الانجليزي». الأسامي اللي المعالج كتبها اتكتبت مرة
# واحدة بلغة الشاشة ساعتها، والعمود واحد — فالشاشة الإنجليزي فضلت تعرض
# «العناية المركزة» و«سرير 3».
#
# **بيتملى بس الاسم اللي البرنامج هو اللي كتبه بالظبط** — اسم القايمة، أو
# اسم القايمة ورقم. اسم العيادة كتبته بإيدها («أوضة الدكتور حسن»)
# ما بيتلمسش: البرنامج ما بيترجمش كلام حد، والغلط هنا اسم إنجليزي غلط
# على سرير في مستشفى شغّالة.

_MARKS = "".join(chr(c) for c in range(0x064B, 0x0653)) + "ٰـ"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _plain(text):
    """الاسم من غير تشكيل ولا تطويل ولا مسافات زيادة — «الحضّانات» هي
    «الحضانات» اللي عيادة كتبتها قبل ما التشكيل يدخل الملف."""
    out = "".join(ch for ch in (text or "") if ch not in _MARKS)
    return " ".join(out.split())


def label(lang, key):
    """اسم من أسامي المعالج بلغة بعينها، من ملف اللغة نفسه — مش من طلب."""
    from app.i18n import _load_translations, _lookup

    full = f"ward_wizard.name_{key.replace('.', '_')}"
    return _lookup(_load_translations(), lang, full)


def named(key, number=None, lang="ar"):
    text = label(lang, key) or key
    return f"{text} {number}" if number else text


def _english_for(name, keys):
    """الإنجليزي لاسم كتبه البرنامج — ``None`` لأي اسم تاني.

    ``keys`` بالترتيب: الأول نوع الصف نفسه، علشان «سرير» سرير ومهد
    وترولّي في نفس الوقت، والإنجليزي بيفرق بينهم.
    """
    plain = _plain(name)
    for key in keys:
        arabic = _plain(label("ar", key))
        english = label("en", key)
        if not arabic or not english:
            continue
        if plain == arabic:
            return english
        head, _, tail = plain.rpartition(" ")
        if head == arabic and tail.translate(_DIGITS).isdigit():
            return f"{english} {tail.translate(_DIGITS)}"
    return None


def _name_keys():
    """Every name the wizard can write, from the language file itself:
    ``(["unit.icu", …], ["space.bay", …], ["bed.bed", …])``."""
    from app.i18n import _load_translations

    names = (_load_translations().get("ar", {}).get("ward_wizard") or {})
    out = {"unit": [], "space": [], "bed": []}
    for key in names:
        if not key.startswith("name_"):
            continue
        group, _, kind = key[len("name_"):].partition("_")
        if group in out and kind:
            out[group].append(f"{group}.{kind}")
    return out["unit"], out["space"], out["bed"]


def fill_english_names():
    """مرة واحدة وقت التحديث، وما بتضرّش لو اتعادت: بتملى ``name_en``
    للأسامي اللي البرنامج كتبها بس، والفاضية بس. بترجع كام صف اتملى."""
    units, spaces, beds = _name_keys()
    filled = 0
    for model, pool in ((Unit, units), (Space, spaces), (Bed, beds)):
        for row in model.query.filter(model.name_en.is_(None)).all():
            own = f"{pool[0].split('.')[0]}.{row.kind}"
            english = _english_for(row.name, [own] + [k for k in pool
                                                      if k != own])
            if english:
                row.name_en = english[:{Unit: 80, Space: 60, Bed: 40}[model]]
                filled += 1
    db.session.flush()
    return filled
