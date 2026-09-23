"""«امسح البيانات التجريبية بس» — وإزاي البرنامج يعرف أنهي صف تجريبي.

**المشكلة إن الصف التجريبي شكله زي الحقيقي بالظبط.** `seed_demo` بيعمل
مرضى وفواتير ومواعيد، وبعد ما يخلص مفيش حاجة في الصف بتقول إنه جه من
هناك.

وفيه تلات طرق، واتنين منهم غلط:

* **عمود `is_demo` على كل جدول** — تغيير واسع في السكيما علشان حاجة
  تشغيلية، وكل جدول جديد محتاج يفتكر.
* **المسح بالاسم** — «يوسف الشريف» اسم تجريبي، وممكن يكون كمان اسم طفل
  حقيقي. ده مسح بيصيب.
* **الزارع يسجّل اللي عمله** ✅ — من غير سكيما، والمسح بيعرف هو بيمسح
  إيه بالظبط بدل ما يخمّن.

---

**والتسجيل بالفرق مش بالتغليف.** `seed_demo` بينده `db.session.add`
عشرين مرة؛ تغليفهم كلهم تعديل واسع وكل سطر جديد بينساه. فالكشف بيتاخد
من **قبل وبعد**: أي `id` ظهر في الوسط هو بتاع الزرع.

**وصف تجريبي حد بنى عليه شغل حقيقي ما بيتمسحش.** مريض تجريبي اتعملت
له فاتورة حقيقية — مسحه بيسيب الفاتورة بتشاور على حد مش موجود، وده
بالظبط الغلط اللي «امسح البيانات» كان واقع فيه. فالمسح بيمشي **من الابن
للأب**، وأي صف لسه حد بيشاور عليه بيتساب — **وبيتقال إنه اتساب**.
"""
import json
from collections import defaultdict

from app.extensions import db
from app.models import Setting
from app.utils import wipe

#: الكشف بيتخزّن هنا — `{اسم الجدول: [ids]}`.
MANIFEST = "demo_manifest"

#: **إعداد مش بيانات.** الزرع بيقلّب مفاتيح — `demo_seeded` وغيرها —
#: والمفتاح اللي اتقلب بقى قرار العيادة، مش صف تجريبي. وزيادة على كده
#: الكشف نفسه بيتخزّن هنا، فتتبّعه بيخلّيه يمسح نفسه.
UNTRACKED = {"settings"}


def tracked_tables():
    """الجداول اللي الكشف بيبصّ فيها — **أوسع من اللي المسح بيفضّيه**.

    ودي مش سهو: «امسح البيانات» **بيسيب** `care_units` و`care_spaces`
    و`care_beds` عن قصد — المبنى مش الشغل اللي حصل فيه. لكن العنبر
    اللي الزرع التجريبي بناه **هو نفسه تجريبي**، ولازم يمشي مع بقيّة
    البيانات التجريبية. فلو الاتنين استعملوا نفس المجموعة، واحد منهم
    هيبقى غلط.

    فالقاعدة هنا أوسع وأبسط: **أي جدول ليه `id`**. والفرق قبل/بعد هو
    اللي بيفلتر — جدول الزرع ما لمسهوش بيطلع فاضي لوحده. يعني جدول
    جديد بيتتبّع **من غير ما حد يفتكره**.
    """
    return {name for name, table in wipe._tables().items()
            if name not in UNTRACKED and table.c.get("id") is not None}


def _ids(table):
    column = table.c.get("id")
    if column is None:
        return set()
    return {row[0] for row in db.session.execute(db.select(column)).all()}


def snapshot():
    """صورة الـids الموجودة دلوقتي — **قبل الزرع**."""
    tables = wipe._tables()
    return {name: _ids(tables[name]) for name in tracked_tables()}


def record(before):
    """اللي ظهر بعد الصورة دي = اللي الزرع عمله. بيتخزّن ويترجّع."""
    tables = wipe._tables()
    made = {}
    for name in tracked_tables():
        fresh = sorted(_ids(tables[name]) - before.get(name, set()))
        if fresh:
            made[name] = fresh
    Setting.set(MANIFEST, json.dumps(made))
    return made


def manifest():
    """اللي الزرع سجّله، أو `{}` لو محدّش زرع."""
    try:
        raw = Setting.get(MANIFEST)
    except Exception:                   # noqa: BLE001 — الإعدادات لسه
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return {name: list(ids) for name, ids in data.items()
            if isinstance(ids, list)}


def forget(names):
    """يشيل الجداول دي من الكشف — **بعد ما حاجة تانية فضّتها**.

    «امسح البيانات» بيفضّي الجداول التشغيلية ويسيب تخطيط المستشفى. لو
    الكشف فضل بالـids القديمة بعده، الخطر مش إنه بيمسح فاضي — الخطر إن
    **الأرقام بتترد**: SQLite بيدّي الصف الجديد أول رقم فاضي، فمريض
    حقيقي اتسجّل بعد المسح ممكن ياخد رقم كان لمريض تجريبي، و«امسح
    التجريبية» بعدها يمسحه وهو مالوش دعوة.

    فاللي اتفضّى بيتشال من الكشف، **واللي ما اتفضّاش بيفضل**: العنبر
    التجريبي بيعيش «امسح البيانات» زي أي عنبر، ولسه ينفع يتشال لوحده
    بعدها.
    """
    plan = manifest()
    if not plan:
        return
    names = set(names)
    rest = {name: ids for name, ids in plan.items() if name not in names}
    Setting.set(MANIFEST, json.dumps(rest) if rest else "")


def _referrers(tables):
    """`{اسم الأب: [الأعمدة اللي بتشاور عليه]}` — مرة واحدة مش كل سؤال."""
    out = defaultdict(list)
    for table in tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                out[fk.column.table.name].append(column)
    return out


def _referenced(table, ids, referrers):
    """الـids اللي لسه فيه صف بيشاور عليها."""
    still = set()
    for column in referrers.get(table.name, ()):
        rows = db.session.execute(
            db.select(column).where(column.in_(list(ids)))
        ).scalars().all()
        still |= {value for value in rows if value is not None}
    return still


def remove():
    """يمسح اللي الزرع عمله — **وبس**. المتصل بيعمل commit.

    بيرجّع ``(اتمسح, اتساب)``: اتنين قاموس بالجدول والعدد. و«اتساب» مش
    فشل — ده صف تجريبي بقى تحت شغل حقيقي، ومسحه كان هيكسر الشغل ده.

    **والمسح بيتكرّر لحد ما يقف، مش لفّة واحدة.** السكيما فيها دواير
    (`visits.based_on_id` ↔ `visit_investigations.visit_id`)، فمفيش
    ترتيب بيخلّص كل حاجة من أول مرة: طرف بيفضل بيشاور على التاني وقت ما
    نعدّي عليه. واللفّة اللي بعدها بتلاقيه فاضي وتمسحه.

    والبديل — نفضّي العمود اللي بيقفل الدايرة قبل ما نبدأ — كان بيلمس
    **صفوف بتتساب**: مريض تجريبي اتبنى عليه شغل حقيقي كان هيفضل موجود
    وعيلته اتشالت من تحته. فالتكرار أغلى شوية وبيسيب اللي بيتساب زي ما
    هو بالظبط — **وبيسيب كمان أهله**، لأن اللي بيشاور على الأب هو نفسه
    اللي بيمنع مسحه.

    ولو فضلت دايرة حقيقية في البيانات نفسها (صفين تجريبيين كل واحد
    بيشاور على التاني)، الاتنين بيتسابوا ويتقال إنهم اتسابوا — أحسن من
    مفتاح أجنبي بيشاور على العدم.

    **والترتيب بقى تسريع مش صحة.** التكرار لوحده بيوصل لنفس النتيجة من
    أي ترتيب — اتقاس: عكس الترتيب ما غيّرش حاجة. اللي الترتيب بيعمله
    إنه بيخلّص الحالة العادية في لفّة واحدة بدل لفّات على ١٧٩ جدول، وكل
    لفّة بتسأل قاعدة البيانات عن كل مفتاح أجنبي.
    """
    plan = manifest()
    if not plan:
        return {}, {}

    tables = wipe._tables()
    wanted = tracked_tables()
    referrers = _referrers(tables)
    order = wipe.delete_order(wanted)
    left = {name: set(ids) for name, ids in plan.items()
            if ids and name in tables}

    removed = defaultdict(int)
    while True:
        gone = 0
        # **من الابن للأب.** لو الأب اتمسح الأول، ابنه التجريبي بيفضل
        # بيشاور عليه — وهو نفس اليُتم اللي بنصلّحه.
        for name in order:
            ids = left.get(name)
            if not ids:
                continue
            table = tables[name]
            # اللي لسه حد بيشاور عليه بعد ما ولاده التجريبيين اتمسحوا،
            # يبقى اللي بيشاور عليه شغل حقيقي.
            free = sorted(ids - _referenced(table, ids, referrers))
            if not free:
                continue
            # **العدد من قاعدة البيانات مش من الكشف.** صف الكشف ممكن
            # يكون اتشال قبل كده بإيد حد، و«اتمسح ١٤٠ صف» وإحنا مسحنا
            # تلاتة رقم بيكدب على اللي قدام الشاشة.
            hit = db.session.execute(
                table.delete().where(table.c.id.in_(free))).rowcount
            if hit:
                removed[name] += hit
            ids -= set(free)
            gone += len(free)
        if not gone:
            break

    kept = {name: len(ids) for name, ids in left.items() if ids}
    Setting.set(MANIFEST, "")
    Setting.set("demo_seeded", "0")
    return dict(removed), kept
