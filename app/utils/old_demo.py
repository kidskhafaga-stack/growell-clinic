"""البيانات التجريبية اللي اتحمّلت **قبل ما الكشف يبقى موجود**.

الكشف (``demo_trace``) بيعرف الصف التجريبي بالـid من ساعة ما اتعمل. لكن
عيادة حمّلت التجريبية قبله عندها ``demo_seeded = 1`` ومفيش كشف — فزرار
«امسح التجريبية بس» ما بيظهرش، والبيانات قاعدة ومحدّش عارف يشيلها غير
بـ«امسح كل حاجة».

**والكشف ما ينفعش يتعمل بالاسم** — «يوسف الشريف» اسم تجريبي وممكن يكون
طفل حقيقي. اللي ينفع هو **الوقت**: الزرع بيعمل كل صفوفه في ثواني، وسجل
النشاط فيه اللحظة دي.

* **اللحظة من سجل النشاط.** «حمّل بيانات تجريبية» بيكتب
  ``data.seed_demo`` *بعد* ما يخلص، فالصفوف قبله بشوية. وويزارد
  الإعداد بيكتب ``settings.facility_setup`` *قبل* ما يزرع، فالصفوف بعده
  بشوية. واللحظة اللي بتتاخد هي اللي فعلاً اتعمل فيها مرضى.
* **الصف اللي اتعمل في الشبّاك ده مرشّح.** والصف اللي من غير تاريخ —
  أو تاريخه قديم عن قصد، زي رسايل «من يومين» — مرشّح **لو بيشاور على
  مرشّح**، وما بيشاورش على حاجة اتعملت بعد الشبّاك.
* **اللي بعد الشبّاك شغل حقيقي**، وعمره ما بيترشّح.
* **ولا سجل النشاط ولا حساب اتفتح بيه.** سجل النشاط هو اللي بيقول مين
  عمل إيه؛ وحساب حد دخل بيه — أو حساب مدير — مش تجريبي حتى لو اتعمل في
  نفس الدقيقة.

**وده تخمين، فمحدّش بيمسح بيه من غير ما يشوفه.** الشاشة بتعرض اللي
لقاه — عدد لكل جدول وأسامي من المرضى — وصاحب العيادة بيأكّد. والتأكيد
بيكتب اللي لقاه **كشف**، والمسح بيعدّي من ``demo_trace.remove`` نفسه:
الابن قبل الأب، واللي شغل حقيقي بيشاور عليه بيتساب ويتقال إنه اتساب.
"""
from collections import defaultdict
from datetime import timedelta

from app.extensions import db
from app.models import ActivityLog, Setting

#: الزرع بيخلص في ثواني؛ الدقيقتين براح للجهاز البطيء.
SPAN = timedelta(minutes=2)
#: بين آخر صف والسطر في السجل — نفس الطلب.
SLACK = timedelta(seconds=5)

#: ما بيترشّحش أبداً. سجل النشاط هو الدليل على اللي حصل؛ والكتالوجات —
#: الأدوية والتطعيمات والتحاليل والحسابات — بتتحمّل **مع** أول تجريبية لو
#: العيادة كانت فاضية، في نفس الدقيقة. دي مرجع العيادة مش بيانات تجريبية:
#: تحليل زيادة في الكتالوج ما بيضرّش، و٢٢ ألف دوا ناقصين بيوقّفوا الروشتة.
NEVER = {
    "activity_log",
    "drugs", "drug_classes", "drug_interactions", "generic_drugs",
    "generic_dose_bands", "high_alert_drugs", "lasa_pairs",
    "vaccines", "vaccine_brands", "vaccine_brand_doses",
    "vaccine_schedule_templates", "vaccine_schedule_doses",
    "investigations", "lookups",
    "accounts", "accounting_periods", "cash_accounts",
}

def applies():
    """فيه تجريبية متحمّلة ومالهاش كشف."""
    from app.utils import demo_trace

    return Setting.get("demo_seeded") == "1" and not demo_trace.manifest()


# ------------------------------------------------------------ the moment ----
def _windows():
    """الشبابيك الممكنة، الأحدث الأول."""
    rows = (ActivityLog.query
            .filter(ActivityLog.action.in_(("data.seed_demo",
                                            "settings.facility_setup")))
            .order_by(ActivityLog.created_at.desc()).all())
    for row in rows:
        if row.action == "data.seed_demo":
            yield row, row.created_at - SPAN, row.created_at + SLACK
        else:
            yield row, row.created_at - SLACK, row.created_at + SPAN


def window():
    """``(السطر, من, لحد)`` للحظة اللي اتعمل فيها مرضى — أو ``None``."""
    from app.models import Patient

    for row, start, end in _windows():
        if Patient.query.filter(Patient.created_at.between(start, end)).first():
            return row, start, end
    return None


# ------------------------------------------------------------ the rows ----
def _in(column, ids):
    return column.in_(sorted(ids))


def _stamp(table):
    """عمود لحظة الإنشاء: ``created_at``، ولو مش موجود أول عمود وقت بيتملي
    لوحده ساعة ما الصف يتعمل (``opened_at`` في يومية الخزنة مثلاً). ومن
    غيرهم ``None`` — والصف بيتلاقي بس لو بيشاور على مرشّح."""
    column = table.c.get("created_at")
    if column is not None:
        return column
    for column in table.columns:
        default = getattr(column.default, "arg", None)
        if isinstance(column.type, db.DateTime) and callable(default):
            return column
    return None


def _clean(table, tables, end):
    """شروط: ولا عمود في الصف بيشاور على صف اتعمل بعد الشبّاك — ده شغل
    حقيقي، وصف بيشاور عليه اتبنى في شغل حقيقي. **سؤال لقاعدة البيانات مش
    لستة في الذاكرة**: عيادة شغّالة سنة فيها مية ألف صف بعد الشبّاك."""
    out = []
    for column in table.columns:
        for fk in column.foreign_keys:
            target = tables.get(fk.column.table.name)
            stamp = _stamp(target) if target is not None else None
            if stamp is None:
                continue
            later = db.select(target.c.id).where(stamp > end)
            out.append(db.or_(column.is_(None), ~column.in_(later)))
    return out


def _born_in(table, tables, start, end):
    """اللي اتعمل في الشبّاك من الجدول ده."""
    q = db.select(table.c.id).where(_stamp(table).between(start, end),
                                    *_clean(table, tables, end))
    if table.name == "users":
        # حساب مدير، أو حساب حد دخل بيه، مش تجريبي — حتى لو اتعمل في
        # نفس الدقيقة.
        q = q.where(table.c.is_super_admin.is_(False),
                    table.c.role != "admin",
                    table.c.last_login_at.is_(None))
    return set(db.session.execute(q).scalars().all())


def find(start, end):
    """``{الجدول: [ids]}`` — اللي باين إن الزرع عمله في الشبّاك ده."""
    from app.utils import demo_trace, wipe

    everything = wipe._tables()
    tables = {name: everything[name]
              for name in demo_trace.tracked_tables() - NEVER}
    found = defaultdict(set)
    for name, table in tables.items():
        if _stamp(table) is not None:
            found[name] = _born_in(table, tables, start, end)

    # صفوف من غير تاريخ — أو تاريخها قديم عن قصد — بتترشّح لو بتشاور على
    # مرشّح. وده بيتكرّر لحد ما يقف: الابن بيترشّح، وابنه اللفّة اللي
    # بعدها.
    while True:
        grew = 0
        for name, table in tables.items():
            links = [_in(column, found[fk.column.table.name])
                     for column in table.columns
                     for fk in column.foreign_keys
                     if found.get(fk.column.table.name)]
            if not links:
                continue
            q = db.select(table.c.id).where(db.or_(*links),
                                            *_clean(table, tables, end))
            created = _stamp(table)
            if created is not None:
                # بعد الشبّاك = شغل حقيقي. قبله = تاريخ قديم عن قصد.
                q = q.where(db.or_(created.is_(None), created < start))
            if found[name]:
                q = q.where(~_in(table.c.id, found[name]))
            fresh = set(db.session.execute(q).scalars().all())
            if fresh:
                found[name] |= fresh
                grew += len(fresh)
        if not grew:
            break
    return {name: sorted(ids) for name, ids in found.items() if ids}


# ------------------------------------------------------------ the screen ----
def preview():
    """اللي الشاشة بتعرضه قبل التأكيد — أو ``None`` لو مفيش لحظة."""
    from app.models import Patient

    moment = window()
    if moment is None:
        return None
    row, start, end = moment
    found = {name: ids for name, ids in find(start, end).items() if ids}
    names = [p.full_name for p in
             Patient.query.filter(Patient.id.in_(found.get("patients", [])))
             .order_by(Patient.id).limit(8).all()]
    return {"at": row.created_at, "action": row.action,
            "tables": sorted(((name, len(ids)) for name, ids in found.items()),
                             key=lambda pair: (-pair[1], pair[0])),
            "total": sum(len(ids) for ids in found.values()),
            "patients": names, "found": found}


def adopt(found):
    """اكتب اللي لقاه كشف — و``demo_trace.remove`` يكمّل من هنا."""
    import json

    from app.utils import demo_trace

    Setting.set(demo_trace.MANIFEST,
                json.dumps({name: sorted(ids) for name, ids in found.items()
                            if ids}))
