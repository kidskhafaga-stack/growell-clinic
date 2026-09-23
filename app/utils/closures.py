"""فتح وقفل قسم أو حيّز أو سرير — **وكتابة الفترة، مش قلب مفتاح**.

الموديل بيقول ليه الفترة؛ ده بيقول إزاي، وإيه اللي بيتمنع.

---

**والمفتاح القديم لسه هو اللي الشاشات بتقراه.** `free_beds` و`board`
بيفلتروا على `is_active` في التلات مستويات من قبل ما الملف ده يتكتب،
وكل شاشة إقامة في البرنامج ماشية عليهم. فالإغلاق **بيكتب الفترة وبيقلب
المفتاح مع بعض**: الفترة هي السجل، والمفتاح هو الكاش اللي الاستعلامات
بتشوفه.

ده بيخلّي إضافة الصيانة **ما تغيّرش حاجة شغالة** — وهو الشرط اللي
اتقال بالنص: *"من غير ما نكسر حاجه شغال"*. والبديل — نشيل الفلاتر
ونحسب الإغلاق في كل استعلام — كان هيمس كل شاشة عنابر في البرنامج
علشان ميزة واحدة.

**وعلشان ما يبقاش فيه حقيقتين، الكتابة في مكان واحد**: زرار «أخرج من
الخدمة» القديم بقى بينده :func:`close` هو كمان. مفيش حتة تانية في
البرنامج بتقلّب `is_active` على سرير.

---

**وقفل القسم ما بيرفضش لو فيه طفل جوّه — وقفل السرير بيرفض.**

والفرق ده مش تناقض، ده نفس السبب من الناحيتين. القاعدة على السرير
مكتوبة في الراوت من زمان:

    A bed with a child in it cannot be taken out of service — the child
    is the reason it is not available, and hiding the bed would hide
    them with it.

سرير فيه طفل **مش متاح أصلاً**، وإخراجه من الخدمة بيخفيه هو والطفل
اللي فيه.

القسم لأ: الصيانة بتتحدّد وإحنا لسه بننقل الأطفال، ورفض القفل لحد ما
آخر واحد يخرج معناه إن القسم يفضل **مفتوح للدخول** طول المدة دي — يعني
حد يدخّل طفل جديد في قسم داخل صيانة. بيتقفل، **وبيتقال إن فيه حد جوّه**
علشان حد ينقله. شوف :func:`stranded`.
"""
from datetime import datetime

from app.extensions import db
from app.models import Bed, Closure, Space, Unit
from app.models.closure import REASON_DOMAIN
from app.utils import lookups

#: أسباب تشغيلية، زي «علبة» و«ثلاجة» — **مش مفردات إكلينيكية**. فالبرنامج
#: يقدر يبدأها بحاجة معقولة، والمستشفى بتزوّد عليها من شاشة القوايم.
BUILT_IN_REASONS = [
    ("maintenance", "صيانة", "Maintenance"),
    ("disinfection", "تعقيم", "Disinfection"),
    ("refurbishment", "تجديد ودهانات", "Refurbishment"),
    ("equipment", "عطل جهاز", "Equipment failure"),
    ("staffing", "نقص تمريض", "Staffing shortage"),
    ("other", "أخرى", "Other"),
]


class Stuck(Exception):
    """اللي بيرفض الفتح: فيه إغلاق تاني فوقه لسه مفتوح."""


class Occupied(Exception):
    """اللي بيرفض قفل سرير فيه طفل — القاعدة القديمة زي ما هي."""


def ensure_reasons():
    """يحط الأسباب المبدئية مرة واحدة. بيرجّع كام واحد اتعمل."""
    # **سؤال واحد مش ستة** — الشاشة بتنده ده كل مرة بتتفتح.
    have = {row[0] for row in db.session.query(lookups.Lookup.key)
            .filter(lookups.Lookup.domain == REASON_DOMAIN).all()}
    made = 0
    for order, (key, name_ar, name_en) in enumerate(BUILT_IN_REASONS):
        if key in have:
            continue
        db.session.add(lookups.Lookup(
            domain=REASON_DOMAIN, key=key, name_ar=name_ar, name_en=name_en,
            sort_order=order, is_system=True))
        made += 1
    if made:
        db.session.flush()
    return made


def level(target):
    """«unit» ولا «space» ولا «bed» — أو `ValueError`.

    **مش `isinstance` مبعترة في كل دالة**: الجواب ده بيتسأل في كل خطوة،
    وتلات نسخ منه بيفترقوا بصمت.
    """
    if isinstance(target, Unit):
        return "unit"
    if isinstance(target, Space):
        return "space"
    if isinstance(target, Bed):
        return "bed"
    raise ValueError(f"not a place: {type(target).__name__}")


def _column(target):
    return {"unit": Closure.unit_id, "space": Closure.space_id,
            "bed": Closure.bed_id}[level(target)]


def current(target):
    """الإغلاق المفتوح على المكان ده بالظبط، أو `None`.

    **على المكان ده بالظبط** — سرير في قسم مقفول مالوش إغلاق بنفسه.
    السؤال ده :func:`covering`.
    """
    return (Closure.query
            .filter(_column(target) == target.id,
                    Closure.reopened_at.is_(None))
            .order_by(Closure.closed_at.desc(), Closure.id.desc())
            .first())


def covering(bed):
    """الإغلاق اللي بيقفل السرير ده فعلاً — **من أي مستوى**.

    قسم داخل صيانة بيقفل كل سرير تحته، والسرير مالوش صف بنفسه. شاشة
    بتسأل السرير لوحده بتقول «شغّال» عن سرير في عنبر مقفول — وده رقم
    غلط في تقرير الإشغال، ودعوة لحد يحطّ فيه طفل.

    بيرجّع الأقرب: السرير، بعدين الحيّز، بعدين القسم.
    """
    for place in (bed, bed.space, bed.space.unit if bed.space else None):
        if place is None:
            continue
        found = current(place)
        if found is not None:
            return found
    return None


def close(target, reason, until=None, note=None, user=None):
    """يقفل المكان: بيكتب الفترة **وبيقلب المفتاح**. المتصل بيعمل commit.

    لو مقفول أصلاً بيرجّع الإغلاق المفتوح زي ما هو — **مش صف تاني**.
    صفّين مفتوحين على نفس المكان بيخلّوا «مقفول من امتى» سؤال بإجابتين.
    """
    reason = (reason or "").strip()
    if not reason:
        # إغلاق من غير سبب هو الصف اللي حد هيبصّ عليه بعد شهر ومش هيعرف
        # يفتحه — وهو نفس الفراغ اللي الجدول اتعمل علشانه.
        raise ValueError("closure needs a reason")

    live = current(target)
    if live is not None:
        return live

    if isinstance(target, Bed):
        from app.utils import beds as ward

        if target.id in ward.occupied_bed_ids():
            raise Occupied(target)

    row = Closure(reason=reason, note=(note or "").strip() or None,
                  until=until, closed_by_id=getattr(user, "id", None))
    setattr(row, f"{level(target)}_id", target.id)
    db.session.add(row)
    target.is_active = False
    if isinstance(target, Bed):
        # الشارة القديمة على الشاشة بتقرا العمود ده. بيتكتب من هنا علشان
        # يفضل صادق، **والسجل لسه هو الفترة**.
        target.out_of_service_note = (row.note or
                                      lookups.label(REASON_DOMAIN, reason))
    db.session.flush()
    return row


def reopen(target, user=None):
    """يفتح المكان. بيرجّع الإغلاق اللي اتقفل، أو `None` لو مكانش مقفول.

    **وبيرفض لو اللي فوقه لسه مقفول**: فتح سرير في عنبر داخل صيانة
    بيخلّيه يبان فاضي في `free_beds` وهو مش شغّال — يعني زرار بيكدب.
    """
    row = current(target)
    if row is None:
        return None

    if isinstance(target, Bed):
        above = next((c for c in (current(target.space),
                                  current(target.space.unit)
                                  if target.space else None) if c), None)
        if above is not None:
            raise Stuck(above)
    elif isinstance(target, Space) and target.unit is not None:
        above = current(target.unit)
        if above is not None:
            raise Stuck(above)

    row.reopened_at = datetime.utcnow()
    row.reopened_by_id = getattr(user, "id", None)
    target.is_active = True
    if isinstance(target, Bed):
        target.out_of_service_note = None
    db.session.flush()
    return row


def history(target, limit=20):
    """كل فترات الإغلاق على المكان ده، الأحدث الأول."""
    return (Closure.query
            .filter(_column(target) == target.id)
            .order_by(Closure.closed_at.desc(), Closure.id.desc())
            .limit(limit).all())


def open_closures():
    """كل إغلاق لسه مفتوح، الأحدث الأول."""
    return (Closure.query
            .filter(Closure.reopened_at.is_(None))
            .order_by(Closure.closed_at.desc(), Closure.id.desc())
            .all())


def open_by_place():
    """`{(المستوى, id): الإغلاق المفتوح}` — **استعلام واحد للشاشة كلها**.

    شاشة التجهيز بتسأل «مقفول؟» عن كل قسم وحيّز وسرير. سؤال لكل واحد
    يبقى ستين استعلام في مستشفى فيها ستين سرير، وده بالظبط الشكل اللي
    سقف الاستعلامات في `test_performance` موجود علشانه.
    """
    out = {}
    # الأحدث الأول، فلو فيه اتنين مفتوحين على نفس المكان (مايحصلش من
    # `close`، بس ممكن من استيراد) الأحدث هو اللي بيكسب — نفس :func:`current`.
    for row in open_closures():
        for level_name in ("unit", "space", "bed"):
            target_id = getattr(row, f"{level_name}_id")
            if target_id is not None:
                out.setdefault((level_name, target_id), row)
    return out


def overdue():
    """إغلاق عدّى الميعاد اللي اتقال وهو لسه مقفول.

    **مش فشل** — ده السؤال اللي محدّش بيفتكر يسأله: «الصيانة دي قالت
    الخميس، إحنا بقالنا أسبوع». واللي مالوش ميعاد مش هنا، لأن «مش عارفين
    هيخلص امتى» قرار اتاخد صح مش تأخير.
    """
    return [row for row in open_closures() if row.overdue]


def stranded():
    """إغلاق مفتوح ولسه فيه طفل جوّه — `[(الإغلاق, [الإقامات])]`.

    **دي الحاجة اللي القفل ما بيرفضهاش وبيقولها.** الصيانة بتحصل والطفل
    موجود، ورفض القفل بيخلّي السجل يكدب. اللي ناقص إن حد يشوف الاسم
    وينقله.
    """
    from app.utils import beds as ward

    by_bed = ward.open_stays_by_bed()
    if not by_bed:
        return []

    # **استعلام واحد لكل الأسرّة المشغولة**، مش واحد لكل سرير: الشاشة
    # دي بتترسم مع لوحة العنابر، وسقف الاستعلامات في `test_performance`
    # موجود علشان الشكل ده بالظبط.
    where = (db.session.query(Bed.id, Bed.space_id, Space.unit_id)
             .join(Space, Bed.space_id == Space.id)
             .filter(Bed.id.in_(list(by_bed))).all())

    out = []
    for row in open_closures():
        stays = [by_bed[bed_id] for bed_id, space_id, unit_id in where
                 if (row.bed_id == bed_id
                     or (row.space_id and row.space_id == space_id)
                     or (row.unit_id and row.unit_id == unit_id))]
        if stays:
            out.append((row, stays))
    return out
