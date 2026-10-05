"""التسليم بين الورديات وبين الأقسام — GAHAR `ACT.08` / `GSR.04`.

> A standardized approach to handover communications, **including an
> opportunity to ask and respond to questions**, is implemented.

**اللي كان موجود قبل الملف ده كان تسليم مسؤولية، مش تسليم وردية.**
`CareResponsibility` (`ACT.07`) بيجاوب «مين الطبيب المسؤول عن الطفل ده»،
والمقيم اللي ماسك نبطشية الليل مش بيبقى المسؤول — بيستلم القسم كله لحد
الصبح ويسلّمه. والتمريض ما كانش ليه أي تسليم خالص.

**وشكل التسليم مش قرارنا.** (أ) بيقول *such as SBAR, ISOBAR, I PASS the
BATON and others* — يعني المستشفى هي اللي بتختار، وكل مستشفى شغّالة
بحاجة. فالشكل إعداد، **لكل نوع تسليم لوحده**: الأطباء ممكن يشتغلوا I-PASS
والتمريض SBAR في نفس المستشفى. والشكل **بيتكتب على التسليم نفسه** وقت ما
اتعمل، علشان مستشفى غيّرت شكلها في مارس ما تعيدش كتابة فبراير.

**ومعظم الكارت بيتملي من الملف.** التشخيص والحساسية والقراءات والتحاليل
المستنية والأدوية المستحقة والقساطر كلها موجودة؛ اللي بيسلّم بيكتب بس
اللي مفيش جدول يعرفه — «خلّي بالك من» — وللطفل اللي محتاجه بس.

**واللي اتقال بيتحفظ زي ما اتقال.** الكارت بيتصوّر (`snapshot`) لحظة
التسليم: لو اتفتح بعد أسبوع لازم يقول اللي المستلم شافه ساعتها، مش
القراءات اللي جت بعده. ودليل ٤ بيطلب *documented … and accessible as
needed*.
"""
from datetime import datetime

from app.extensions import db

#: (ب) بين الورديات في نفس القسم، أو بين قسمين.
SHIFT, TRANSFER = "shift", "transfer"
OCCASIONS = (SHIFT, TRANSFER)

#: مين بيسلّم لمين. التسليم بين قسمين مالوش نوع: اللي بيستقبل الطفل في
#: القسم التاني ممكن يكون طبيب أو ممرضة.
MEDICAL, NURSING = "medical", "nursing"
DISCIPLINES = (MEDICAL, NURSING)

#: الأشكال اللي (أ) بيسمّيها. ISBAR هو SBAR بخطوة تعريف قبله، وI-PASS ليه
#: خمس خطوات منهم «شدّة الحالة» و«المستلم بيلخّص».
METHODS = ("sbar", "isbar", "ipass")

#: I-PASS (I): شدّة الحالة — كلمة من تلاتة، مش رقم البرنامج اخترعه.
SEVERITIES = ("stable", "watcher", "unstable")


class Handover(db.Model):
    """تسليم واحد: وردية قسم، أو طفل اتنقل من قسم لقسم."""

    __tablename__ = "handovers"

    id = db.Column(db.Integer, primary_key=True)
    occasion = db.Column(db.String(10), nullable=False, default=SHIFT,
                         index=True)
    #: فاضي في تسليم بين قسمين.
    discipline = db.Column(db.String(10), index=True)
    #: الشكل اللي اتسلّم بيه، متصوّر من إعداد المستشفى ساعتها.
    method = db.Column(db.String(8), nullable=False, default="sbar")

    #: القسم اللي اتسلّم — أو اللي استقبل الطفل في النقل. **فاضي** يعني
    #: كل الأقسام: مقيم الليل بيمسك المستشفى كلها، وتلات تسليمات لتلات
    #: أقسام كانت هتخلّيه يسلّم واحد وينسى اتنين.
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        index=True)
    #: في النقل بس: القسم اللي الطفل جه منه.
    from_unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"))

    handed_by = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    handed_at = db.Column(db.DateTime, default=datetime.utcnow,
                          nullable=False, index=True)
    #: لمين اتعرض، لو اللي سلّم عارف. اللي يستلم فعلاً ممكن يكون غيره.
    offered_to = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: حاجة تخص القسم كله مش طفل بعينه — جهاز عطلان، سرير مقفول.
    note = db.Column(db.Text)

    accepted_by = db.Column(db.Integer, db.ForeignKey("users.id"),
                            index=True)
    accepted_at = db.Column(db.DateTime, index=True)
    #: I-PASS (S الأخيرة): المستلم لخّص اللي سمعه.
    synthesis = db.Column(db.Boolean)

    unit = db.relationship("Unit", foreign_keys=[unit_id])
    from_unit = db.relationship("Unit", foreign_keys=[from_unit_id])
    giver = db.relationship("User", foreign_keys=[handed_by])
    offered = db.relationship("User", foreign_keys=[offered_to])
    receiver = db.relationship("User", foreign_keys=[accepted_by])
    items = db.relationship("HandoverItem", back_populates="handover",
                            cascade="all, delete-orphan",
                            order_by="HandoverItem.id")

    @property
    def is_open(self):
        return self.accepted_at is None

    @property
    def open_questions(self):
        return [i for i in self.items if i.question and not i.answer]

    def minutes_to_accept(self):
        if self.accepted_at is None or self.handed_at is None:
            return None
        return max(0, int((self.accepted_at - self.handed_at)
                          .total_seconds() // 60))

    def __repr__(self):
        return f"<Handover {self.id} {self.occasion} {self.discipline}>"


class HandoverItem(db.Model):
    """طفل واحد في التسليم: كارته، واللي اتكتب عنه، والسؤال والرد."""

    __tablename__ = "handover_items"

    id = db.Column(db.Integer, primary_key=True)
    handover_id = db.Column(db.Integer, db.ForeignKey("handovers.id"),
                            nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: الكارت زي ما المستلم شافه — JSON.
    snapshot = db.Column(db.Text)
    #: «خلّي بالك من» — الحاجة الوحيدة اللي بتتكتب.
    watch = db.Column(db.Text)
    severity = db.Column(db.String(10))

    #: الفرصة اللي المعيار بيطلبها للسؤال والرد.
    question = db.Column(db.Text)
    asked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    asked_at = db.Column(db.DateTime)
    answer = db.Column(db.Text)
    answered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    answered_at = db.Column(db.DateTime)

    handover = db.relationship("Handover", back_populates="items")
    admission = db.relationship("Admission")
    patient = db.relationship("Patient")
    asker = db.relationship("User", foreign_keys=[asked_by])
    answerer = db.relationship("User", foreign_keys=[answered_by])

    @property
    def card(self):
        import json

        try:
            return json.loads(self.snapshot) if self.snapshot else {}
        except ValueError:
            return {}

    def __repr__(self):
        return f"<HandoverItem {self.id} h={self.handover_id}>"
