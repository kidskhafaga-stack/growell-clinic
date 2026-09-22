"""الألم — GAHAR `ICD.09`.

النية بتبدأ بجملة مش إجرائية، وهي اللي بتشرح ليه البند ده موجود أصلاً:

> Each patient has the **right to a pain-free life**.

والمعيار بيقسّم الشغل لتلات حاجات مختلفة، والبرنامج كان عنده **رقم بس**:

> Inpatients and outpatients are **screened** for pain, **assessed** whenever
> pain is present, and **managed** accordingly.

---

**والفرق بين الفرز والتقييم هو كل التصميم هنا.**

الفرز بيحصل **لكل طفل** — سؤال واحد بأداة. والتقييم بيحصل **لما يطلع فيه
ألم بس**، وبيطلب خمس حاجات (ب). فجدولين، لأن دول مش نوعين من صف واحد:
فرز ممكن يخلص من غير تقييم (مفيش ألم)، وتقييم واحد ممكن يتعمل له خمس
إعادات فرز والتقييم زي ما هو.

**وأوحش صف هنا هو «اتفرز وطلع فيه ألم ومحدّش قيّمه»** — لأنه بيبان
مكتمل: فيه أداة، وفيه رقم، وفيه وقت، وفيه اسم اللي عمله.

---

**والأداة بتاعة المستشفى مش بتاعتنا.** عمود `Observation.pain_score`
مكتوب جنبه `0–10, the faces/numeric scale` — يعني البرنامج كان **مفترض
المقياس**. والقايمة دلوقتي `Lookup` بدومين `pain_tool` وبتبدأ فاضية.
"""
from datetime import datetime

from app.extensions import db

#: قايمة العيادة — بتبدأ فاضية. شوف `utils/lookups`.
TOOL_DOMAIN = "pain_tool"

#: (ب) *pain intensity, character, location, frequency, and duration* —
#: خمسة بالاسم، وكل واحد فيهم سؤال تاني خالص.
ELEMENTS = ("intensity", "character", "location", "frequency", "duration")


class PainScreen(db.Model):
    """فرز واحد: أداة، ورقم، وهل فيه ألم."""

    __tablename__ = "pain_screens"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    #: **الجولة اللي الرقم اتقاس فيها**, لما يكون اتقاس في جولة ملاحظات.
    #:
    #: بيشاور مش بينسخ: الرقم بتاع الشارت مكانه `Observation.pain_score`
    #: زي ما هو، والصف ده بيقول إن الفرز ده هو نفس اللحظة دي. نسخه كان
    #: هيخلّي شارت الملاحظات وسجل الألم يقولوا رقمين لنفس الساعة.
    observation_id = db.Column(db.Integer, db.ForeignKey("observations.id"),
                               nullable=True, index=True)

    #: أنهي أداة — مفتاح من قايمة العيادة.
    tool_key = db.Column(db.String(40), index=True)
    score = db.Column(db.Integer)

    #: **فيه ألم ولا لأ — واللي بيفرز هو اللي بيقول.**
    #:
    #: والبرنامج **مش بيحوّل الرقم لحكم**. كل أداة ليها مداها وقراءتها،
    #: وحدّ زي «٤ فأكتر يبقى ألم» رقم إكلينيكي — نفس نوع الرقم اللي
    #: البرنامج بيرفض يخترعه في الفرز والتسكين واليرقان. اللي ماسك
    #: الأداة بيقراها ويقول.
    has_pain = db.Column(db.Boolean, nullable=False, default=False,
                         index=True)

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient", backref="pain_screens")
    visit = db.relationship("Visit", backref="pain_screens")
    admission = db.relationship("Admission", backref="pain_screens")
    observation = db.relationship("Observation")
    by = db.relationship("User", foreign_keys=[by_id])

    def __repr__(self):
        return f"<PainScreen p={self.patient_id} pain={self.has_pain}>"


class PainAssessment(db.Model):
    """(ب) التقييم الكامل — خمس حقايق، وخطة."""

    __tablename__ = "pain_assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: الفرز اللي طلّع الألم. **مطلوب**: دليل ٤ بيقول إن التقييم بيتعمل
    #: *when pain is identified **from the screening*** — فتقييم من غير
    #: فرز هو تقييم مالوش سبب مكتوب.
    screen_id = db.Column(db.Integer, db.ForeignKey("pain_screens.id"),
                          nullable=False, index=True)

    #: (ب) الخمسة. **نص مش رقم** في أربعة منهم، لأن «فين» و«شكله إيه»
    #: و«كل قد إيه» و«بقاله قد إيه» إجابات كلام. والشدّة رقم الأداة.
    intensity = db.Column(db.String(40))
    character = db.Column(db.String(120))
    location = db.Column(db.String(120))
    frequency = db.Column(db.String(80))
    duration = db.Column(db.String(80))

    #: (د) الخطة. دليل ٥ بيطلبها **مكتوبة في الملف** جنب الباقي.
    plan = db.Column(db.Text)

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient", backref="pain_assessments")
    # `uselist=False` على العلاقة دي بتوصف الاتجاه ده هي؛ الاتجاه
    # التاني محتاج `backref()` صريحة — من غيرها `screen.assessment`
    # بترجّع **قايمة**، وقايمة فاضية مش `None`، فالحارس اللي بيمنع
    # التقييم مرتين كان بيرفض التقييم الأول كمان.
    screen = db.relationship("PainScreen",
                             backref=db.backref("assessment", uselist=False),
                             uselist=False)
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def managed(self):
        """(د) — فيه خطة مكتوبة فعلاً.

        تقييم من غير خطة هو نص المعيار: *assessed … **and managed
        accordingly***، والكلمة التانية مش زينة.
        """
        return bool((self.plan or "").strip())

    def __repr__(self):
        return f"<PainAssessment p={self.patient_id}>"
