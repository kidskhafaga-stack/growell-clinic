"""القسم داخل صيانة — فترة، مش مفتاح.

*"فى مستشفى القسم فى الصيانة… لازم يكون فى اضافة فترة الاغلاق وكده لازم
نراعيه، حضانة فى فترة صيانة و وحدة كاملة مش شغالة علشان داخله صيانة او
جزء."*

**واللي كان موجود يجاوب تلت السؤال.** `Bed.is_active` مع
`out_of_service_note` — مفتاح على **السرير بس**، من غير مدة ولا سبب
مقنّن ولا تاريخ. والقسم كله والحيّز ماكانش ليهم حاجة خالص، مع إن دول
اللي بيتقفلوا للصيانة فعلاً: حضّانة بتتعقّم، وعنبر بيتدهن.

---

**الفترة مش مفتاح، للسبب اللي `BedStay` نفسها كاتباه:**

    The old row keeps its hours. Overwriting ``bed_id`` in place would
    answer "where is this child now" and silently rewrite every earlier
    day of the stay.

مفتاح بيجاوب «القسم مقفول دلوقتي؟». وأول ما يفتح، **سؤال «كان مقفول
كام يوم الشهر اللي فات؟» ما بقاش ليه إجابة** — وهو بالظبط الرقم اللي
المستشفى بتقوله في تقرير الإشغال، لأن سرير مقفول للصيانة مش سرير فاضي
محدّش نام فيه.

---

**والمخطط غير اللي حصل — عمودين مش واحد.**

`until` هو **الكلام**: «هيخلص الخميس». و`reopened_at` هو **اللي حصل**:
فتح الأحد. عمود واحد للاتنين بيمسح الفرق، وساعتها مفيش شاشة تقدر تقول
«الصيانة دي عدّت ميعادها بتلات أيام» — وهي المعلومة الوحيدة اللي بتخلّي
حد يسأل.

و`until` **nullable**: «مش عارفين هيخلص امتى» إجابة حقيقية، وتاريخ
مخترع أسوأ من فراغ.

---

**والمستوى واحد من تلاتة، ومش أكتر.** قسم أو حيّز أو سرير — والصف
بيمسك عمود واحد بس منهم. صف بيشاور على قسم **و**سرير هو سؤال مالوش
إجابة: هو القسم المقفول ولا السرير؟ والحارس في :func:`level` بيرفض.
"""
from datetime import datetime

from app.extensions import db

#: أسباب الإغلاق — **قايمة العيادة تقدر تزوّد عليها** (`utils/lookups`)،
#: لأن «تعقيم بعد حالة معدية» سبب حقيقي في مستشفى ومالوش وجود في تانية.
REASON_DOMAIN = "closure_reason"


class Closure(db.Model):
    """فترة إغلاق واحدة على قسم أو حيّز أو سرير."""

    __tablename__ = "care_closures"

    id = db.Column(db.Integer, primary_key=True)

    # **واحد بس من التلاتة.** الحارس في `utils/closures.close`.
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=True, index=True)
    space_id = db.Column(db.Integer, db.ForeignKey("care_spaces.id"),
                         nullable=True, index=True)
    bed_id = db.Column(db.Integer, db.ForeignKey("care_beds.id"),
                       nullable=True, index=True)

    #: مفتاح من :data:`REASON_DOMAIN`. **مش nullable**: إغلاق من غير سبب
    #: هو بالظبط الصف اللي حد هيبصّ عليه بعد شهر ومش هيعرف يفتحه.
    reason = db.Column(db.String(40), nullable=False)
    note = db.Column(db.String(200))

    closed_at = db.Column(db.DateTime, default=datetime.utcnow,
                          nullable=False, index=True)
    #: **المخطط**: المفروض يفتح إمتى. فاضي = محدّش قال.
    #:
    #: **يوم مش لحظة.** «هيخلص الخميس» اسم يوم؛ لو اتخزّن ساعة، نص الليل
    #: بتاع الخميس كان هيخلّيه «متأخر» من أول دقيقة في اليوم اللي المفروض
    #: يخلص فيه — يعني متأخر بيوم قبل ما يتأخر.
    until = db.Column(db.Date, index=True)
    #: **اللي حصل**: فتح إمتى فعلاً. فاضي = **لسه مقفول**.
    reopened_at = db.Column(db.DateTime, index=True)

    closed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reopened_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    unit = db.relationship("Unit", foreign_keys=[unit_id])
    space = db.relationship("Space", foreign_keys=[space_id])
    bed = db.relationship("Bed", foreign_keys=[bed_id])
    closed_by = db.relationship("User", foreign_keys=[closed_by_id])
    reopened_by = db.relationship("User", foreign_keys=[reopened_by_id])

    @property
    def is_open(self):
        """لسه مقفول — **محسوب، مش عمود**.

        عمود `is_closed` كان هيبقى حقيقة تانية جنب `reopened_at`، وأول
        ما الاتنين يختلفوا مفيش حد يعرف مين الصح فيهم.
        """
        return self.reopened_at is None

    @property
    def overdue(self):
        """عدّى ميعاده وهو لسه مقفول.

        **بيرجّع `False` لو محدّش قال ميعاد** — مش `None`: «مفتوح من غير
        ميعاد» مش تأخير، ده قرار اتاخد صح.
        """
        if self.until is None or not self.is_open:
            return False
        from app.utils.clock import local_today

        # بالتاريخ المحلي: اليوم اللي العيادة عايشاه، مش يوم جرينتش.
        return local_today() > self.until

    def __repr__(self):
        level = ("unit" if self.unit_id else
                 "space" if self.space_id else "bed")
        return f"<Closure {level} {self.reason}>"
