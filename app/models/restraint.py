"""تقييد أو عزل واحد، من الأمر اللي سمح بيه لحد ما اتشال — GAHAR `CSS.12`.

دليل ٥ بيقول بالنص: *"Restraints and seclusions are **recorded in the
patient's medical record**"*. والسياسة (أ)–(ط) فيها خمسة بنود الملف هو اللي
بيثبتهم، وهُمّا اللي الجدول ده اتبنى عليهم:

> (b) Requirements for **clear physician order** …
> (d) The **least restrictive** methods are to be used as appropriate.
> (f) **Monitoring and reassessment** during use.
> (g) **Renewal** of the restraint order is based on continuing needs …
> (i) **Termination** … is according to defined criteria.

---

**والبند (ز) هو اللي المعيار كله موجود علشانه.** أمر تقييد ليه مدة، وتجديده
قرار جديد لازم يتاخد تاني. وأخطر حاجة ممكن تحصل هنا مش إن حد ينسى يكتب —
دي إن **الأمر يخلص والتقييد فاضل مربوط**، ومحدّش على وجه الأرض عنده شاشة
بتقول له كده. فالمدة عمود (`valid_until`)، والتجديد **صف جديد** مربوط
بالقديم مش تعديل عليه: تعديل التاريخ كان هيمسح إن حد قرّر مرتين.

**والمراقبة (و) مش جدول تاني.** القراءات أثناء التقييد هي ملاحظات الطفل
العادية متعلّمة بـ`Observation.restraint_id` — نفس اللي نقل الدم عمله
بالظبط، وللسبب نفسه: جدول تاني كان هيحطّ نوع واحد من الحقايق في مكانين،
وكان هيشيل قراءات التقييد من شارت الطفل.

**والبرنامج ما بيخترعش «الأقل تقييداً».** (د) بيقول *as appropriate*، والحكم
ده الطبيب بتاعه. اللي بيتسجّل: النوع (تصنيف تشغيلي)، والطريقة **بكلام
المستشفى**، و**اللي اتجرّب قبله** — لأن «الأقل تقييداً» مش صفة في القائمة،
دي حاجة بتتثبت بإن فيه حاجة أخف اتجرّبت الأول.
"""
from datetime import datetime

from app.extensions import db

#: تصنيف تشغيلي، مش تدرّج إكلينيكي. التلاتة دول أسماء موجودة في عنوان
#: المعيار نفسه وفي الممارسة، والتفصيلة بتتكتب في `method` بكلام المستشفى.
PHYSICAL, CHEMICAL, SECLUSION = ("physical", "chemical", "seclusion")
KINDS = (PHYSICAL, CHEMICAL, SECLUSION)


class Restraint(db.Model):
    """One episode of restraint or seclusion."""

    __tablename__ = "restraints"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # ممكن يحصل في قسم داخلي أو في الطوارئ. الاتنين اختياريين لأن الحدث
    # بيخصّ الطفل، والمكان تفصيلة فيه — نفس الدرس اللي الطوارئ علّمته.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    kind = db.Column(db.String(16), nullable=False, index=True)
    # بكلام المستشفى: «حزام صدر» · «قفازات» · «غرفة هدوء». البرنامج مالوش
    # قايمة أدوات، والمستشفى عندها سياستها.
    method = db.Column(db.String(120))

    # (أ) المعايير: ليه اتعمل. مطلوبة — تقييد من غير سبب مكتوب هو بالظبط
    # اللي المعيار ده موجود يمنعه.
    reason = db.Column(db.Text, nullable=False)
    # (د) إيه اللي اتجرّب قبل كده. «الأقل تقييداً» بتتثبت بده، مش بوصف.
    alternatives = db.Column(db.Text)

    # (ب) أمر الطبيب. مش اختياري: ده نص البند.
    ordered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=False)
    ordered_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    # (ج) مين طبّقه — ناس مؤهّلين، والملف بيقول مين.
    applied_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    started_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    # (ز) الأمر ليه مدة. `None` معناها محدّش حطّ مدة — وده نفسه ملاحظة.
    valid_until = db.Column(db.DateTime, index=True)
    # التجديد صف جديد بيشاور على القديم، مش تعديل على تاريخه.
    renews_id = db.Column(db.Integer, db.ForeignKey("restraints.id"),
                          nullable=True, index=True)

    # (ط) الإنهاء: إمتى وعلى أي أساس.
    ended_at = db.Column(db.DateTime, index=True)
    ended_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    ended_reason = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="restraints")
    ordered_by = db.relationship("User", foreign_keys=[ordered_by_id])
    applied_by = db.relationship("User", foreign_keys=[applied_by_id])
    ended_by = db.relationship("User", foreign_keys=[ended_by_id])
    renews = db.relationship("Restraint", remote_side=[id])

    @property
    def is_on(self):
        """لسه مربوط. مشتقّة من الوقت، مش عمود حالة ممكن يخالفه."""
        return self.ended_at is None

    def expired_at(self, now=None):
        """الأمر عدّى مدته والتقييد لسه شغّال؟ يرجّع من إمتى.

        **دي الملاحظة اللي المعيار (ز) موجود علشانها**، والحاجة اللي مفيش
        شاشة في أي مكان بتقولها: مش «حد نسي يكتب» — دي «الأمر خلص والطفل
        لسه مربوط».
        """
        if not self.is_on or self.valid_until is None:
            return None
        moment = now or datetime.utcnow()
        return self.valid_until if moment > self.valid_until else None

    @property
    def minutes(self):
        """قد إيه قعد مربوط، أو قد إيه مربوط لحد دلوقتي."""
        end = self.ended_at or datetime.utcnow()
        return int((end - self.started_at).total_seconds() // 60)

    def __repr__(self):
        return f"<Restraint {self.kind} patient={self.patient_id}>"
