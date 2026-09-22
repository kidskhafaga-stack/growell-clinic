"""تقييم التمريض — GAHAR `ICD.07`.

النية بتعرّفه بجملة واسعة:

> Nursing assessment is gathering information about a patient's
> **physiological, psychological, sociological, and spiritual** status by a
> licensed nurse.

وبعدين بتسمّي محتوى السجل الأدنى في ستة بنود — **وتلاتة منهم البرنامج
بيعرفهم أصلاً**:

* **(أ)** العلامات الحيوية والطول والوزن → `Observation` و`Measurement`.
* **(ب)** تقييم السقوط → `RiskAssessment` نوع `fall`.
* **(ج)** الفرز المطلوب — ألم وفراش وتغذية → `PainScreen`، ونوع
  `pressure`، و`NutritionAssessment`.
* **(د)** المجرى الهوائي والتنفّس والدورة والوعي والجلد والترطيب →
  **مفيش**.
* **(هـ)** المخرجات، لما تلزم → **مفيش**.
* **(و)** تقييم مفصّل للجهاز اللي عليه الشكوى → **مفيش**.

**فالسجل ده قارئ أكتر منه كاتب** — نفس قسمة `CarePlan` بالظبط، واللي
مكتوب هناك بالحرف: *"the program assembles what the record already holds,
and a person writes only what nothing in the record could know"*.

ونسخ (أ) و(ب) و(ج) هنا كان هيخلّي نسختين من كل قراءة، والنسخة اللي على
الورقة دي هي اللي هتبوظ — نفس حجّة الإحالة والدوا في `ACT.14`.
"""
from datetime import datetime

from app.extensions import db

#: التقييم الأول عند الدخول، وإعادة التقييم بعده. **مهلتين مختلفتين**:
#: دليل ٣ بيقول *upon admission within the timeframe*، ودليل ٤ بيقول
#: *at the frequency* — دول رقمين مختلفين في سياسة المستشفى، وخلطهم
#: بيخلّي واحد فيهم يختفي.
INITIAL, REASSESSMENT = ("initial", "reassessment")
KINDS = (INITIAL, REASSESSMENT)

#: (د) الستة بالاسم. **كل واحد فيهم ملاحظة لوحدها**: ممرضة بتكتب
#: «الجلد سليم» مش بتكون قالت حاجة عن الترطيب، وخانة واحدة للستة
#: بتخلّي أول إجابة تنوب عن الباقي.
ABCDE = ("airway", "breathing", "circulation", "disability", "skin",
         "hydration")


class NursingAssessment(db.Model):
    """تقييم تمريض واحد — الأول أو إعادة."""

    __tablename__ = "nursing_assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: **مطلوبة.** دليل ٣ بيقول *upon admission*، وتقييم تمريض من غير
    #: إقامة مالوش اللحظة اللي المعيار بيقيس منها.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    kind = db.Column(db.String(14), nullable=False, default=INITIAL,
                     index=True)

    # ---- (د) ------------------------------------------------------------
    airway = db.Column(db.String(120))
    breathing = db.Column(db.String(120))
    circulation = db.Column(db.String(120))
    disability = db.Column(db.String(120))
    skin = db.Column(db.String(120))
    hydration = db.Column(db.String(120))

    #: (هـ) **«لما تلزم»** — ونصّها في المعيار *(as relevant)*. فالعمود ده
    #: مش بيتعدّ ناقص: طفل مالوش مخرجات تتقاس ورقته كاملة، وعدّه كان
    #: هيخلّي القايمة تصرخ على كل تقييم.
    outputs = db.Column(db.Text)

    #: (و) الجهاز اللي عليه الشكوى. **نص، لأن ده اللي بيفرّق بين تقييم
    #: وقايمة علامات**: «الصدر: صفير في القاعدتين» حاجة محدّش تاني في
    #: البرنامج بيعرفها.
    focus = db.Column(db.Text)

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient", backref="nursing_assessments")
    admission = db.relationship("Admission", backref="nursing_assessments")
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def is_initial(self):
        return self.kind == INITIAL

    def __repr__(self):
        return f"<NursingAssessment {self.kind} adm={self.admission_id}>"
