"""القساطر والأنابيب — GAHAR `CSS.03`.

النية بتقول الخطر بالنص:

> During care, these tubes and catheters may be **misconnected**, leading to
> the administration of the wrong material via the wrong route, resulting in
> **grave consequences**.

ودليل ٤ بيقول *"Management and use of tubes and catheters are **recorded in
patient medical records**"*.

---

**والسياسة بتسمّي القساطر عالية الخطورة بالاسم** — (ب):

> Labelling of **high-risk catheters (e.g., arterial, epidural, intrathecal)**
> and avoidance of using catheters with injection ports for these
> applications.

**فـ«عالية الخطورة» بتتحسب من النوع، مش علامة حد بيحطّها.** علامة كانت
هتسمح لواحد يقول إن الإيبيدورال مش عالي الخطورة — والمعيار هو اللي سمّى
التلاتة، فالبرنامج بيقراهم منه. والعيادة تقدر تزوّد على القايمة (نوع
«تاني» بتوصيفه)، بس ما تقدرش تنزّل واحد من التلاتة.

**والخريطة مش جدول تاني.** (د) بيطلب *catheter maps as part of handover
communications* — ودي **قراية** لللي مركّب دلوقتي، مش حاجة تتكتب وتتحدّث
ورا الصفوف. خريطة متخزّنة كانت هتفرق عن الصفوف أول مرة حد ينسى يحدّثها،
وساعتها التسليم بيتقرا من الحاجة الغلط.

**والشيل لحظة مش مسح.** قسطرة اتركّبت واتشالت تاريخ الملف محتاجه: مدة
بقائها هي اللي بتقول كان فيه خطر عدوى قد إيه، وصف اتمسح بيشيل السؤال
مش بيجاوبه.
"""
from datetime import datetime

from app.extensions import db

#: التلاتة اللي المعيار سمّاهم بالنص — (ب). القايمة دي من الكتاب، مش
#: من عندنا، وعلشان كده مش إعداد.
ARTERIAL, EPIDURAL, INTRATHECAL = ("arterial", "epidural", "intrathecal")
HIGH_RISK = (ARTERIAL, EPIDURAL, INTRATHECAL)

#: والباقي أنواع عادية بتتشاف كل يوم في قسم أطفال. «تاني» موجود علشان
#: العيادة تكتب اللي إحنا ما نعرفوش بدل ما تحشره في نوع قريب — ونوع
#: غلط في خريطة التسليم أوحش من نوع مكتوب بالإيد.
PERIPHERAL, CENTRAL, UMBILICAL = ("peripheral", "central", "umbilical")
URINARY, NASOGASTRIC, CHEST, DRAIN = ("urinary", "nasogastric", "chest",
                                      "drain")
OXYGEN, OTHER = ("oxygen", "other")
KINDS = (PERIPHERAL, CENTRAL, UMBILICAL, ARTERIAL, EPIDURAL, INTRATHECAL,
         URINARY, NASOGASTRIC, CHEST, DRAIN, OXYGEN, OTHER)


class Line(db.Model):
    """One catheter or tube, from the moment it went in to the moment it
    came out."""

    __tablename__ = "lines"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    kind = db.Column(db.String(20), nullable=False, index=True)
    #: وصف العيادة لما النوع يكون «تاني» — بكلامهم، لأن اللي إحنا ما
    #: نعرفوش مش هنسمّيه بالنيابة عنهم.
    kind_note = db.Column(db.String(80))
    #: فين بالظبط — «يد يمين» · «تحت الترقوة الشمال». ده اللي بيخلّي
    #: خريطة التسليم تنفع تتتبّع (ج).
    site = db.Column(db.String(80))
    size = db.Column(db.String(20))

    #: (ب) الملصق. **نص، مش علامة** — المعيار عايز القسطرة تبقى مكتوب
    #: عليها إيه هي، واللي بيبص عليها بيقرا كلام مش بيشوف صح.
    label = db.Column(db.String(80))

    inserted_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False, index=True)
    inserted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    removed_at = db.Column(db.DateTime, index=True)
    removed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: اتشالت ليه — خلصت، ولا اتسدّت، ولا فيه التهاب. ده بيفرق.
    removal_reason = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="lines")
    inserted_by = db.relationship("User", foreign_keys=[inserted_by_id])
    removed_by = db.relationship("User", foreign_keys=[removed_by_id])

    @property
    def in_place(self):
        return self.removed_at is None

    @property
    def high_risk(self):
        """**من النوع، مش من علامة** — `CSS.03` (ب) سمّى التلاتة بالنص.

        علامة كانت هتسمح لواحد يقول إن الإيبيدورال مش عالي الخطورة،
        وساعتها الفاحص اللي بيدوّر على الملصق الناقص ما بيشوفهاش.
        """
        return self.kind in HIGH_RISK

    @property
    def labelled(self):
        return bool((self.label or "").strip())

    @property
    def days_in(self):
        """قد إيه وهي مركّبة، بالأيام — واللي لسه مركّبة بتتحسب لدلوقتي.

        ودي اللي بتخلّي «القسطرة دي بقالها أد إيه؟» سؤال ليه إجابة بدل
        ما حد يعدّ على ورق التسليم.
        """
        end = self.removed_at or datetime.utcnow()
        return int((end - self.inserted_at).total_seconds() // 86400)

    def __repr__(self):
        return f"<Line {self.kind} patient={self.patient_id}>"
