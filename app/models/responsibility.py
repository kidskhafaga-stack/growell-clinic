"""مين الطبيب المسؤول — GAHAR `ACT.07`.

النية بتسمّي العاقبة بالنص:

> **Misunderstandings about who** among the healthcare team **is responsible**
> for a patient's care may compromise that care and result in an adverse
> event and increased medico-legal risk.

**والبرنامج كان بيقول نص الإجابة.** `Admission.doctor_id` موجود —
وnullable. يعني ممرضة بتدخّل طفل، والعمود بيفضل فاضي **طول الإقامة**،
ومفيش شاشة بتقول كده.

---

**بس العمود نفسه مش الشكل الصح، حتى لو اتملا.**

> The term most responsible physician refers to the physician who has overall
> responsibility … **at a specific point in time**.

عمود واحد بيجاوب «مين مسؤول دلوقتي». وأول ما المسؤولية تتنقل، بيتكتب
فوقه — **وسؤال «مين كان مسؤول يوم التلات» ما بقاش ليه إجابة**، وهو
بالظبط السؤال اللي بيتسأل بعدين.

**والبرنامج خد القرار ده قبل كده**، في نفس الجدول: `BedStay` بتقول
*"The old row keeps its hours. Overwriting ``bed_id`` in place would answer
'where is this child now' and silently rewrite every earlier day of the
stay"*. «مين مسؤول» نفس الشكل بالظبط — وده اللي المعيار كاتبه صراحة.

فالمسؤولية **فترات**: كل صف له بداية ونهاية، والمفتوح هو اللي دلوقتي.

---

**والتسليم طرفين، مش واحد.** (د) بيقول *clear identification of
responsibility **between the transfer of responsibility parties*** —
الكلمة بالجمع. وطبيب بيسلّم ومحدّش استلم هو بالظبط سوء الفهم اللي النية
بتحذّر منه: الأول فاكر إنه مشي، والتاني مش عارف إنه بقى مسؤول.

فالتسليم بيتقفل بتوقيعين، **واللي سلّم ما يقدرش يستلم لنفسه** — نفس
قاعدة `VerbalOrder` بالظبط.
"""
from datetime import datetime

from app.extensions import db


class CareResponsibility(db.Model):
    """فترة واحدة: طبيب مسؤول عن إقامة، من إمتى لإمتى."""

    __tablename__ = "care_responsibilities"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    #: **مش nullable.** صف مسؤولية من غير طبيب هو نفس الفراغ اللي
    #: الجدول ده اتعمل علشانه.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)

    since = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                      index=True)
    #: فاضي يعني **هو المسؤول دلوقتي**.
    until = db.Column(db.DateTime, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    # ---- التسليم: دليل ٤ و(ج) و(د) ----------------------------------
    #
    # الصف ده هو **الخارج**، وهو اللي عارف الناقص. (ج) بيطلب إن
    # *assessment and care plan, **including pending steps*** تتنقل —
    # والخطوات المعلّقة هي الحاجة الوحيدة اللي مفيش جدول تاني بيعرفها:
    # «مستني صورة الصدر» مش مكتوبة في أي مكان تاني في البرنامج.
    #
    # وباقي الـ(ج) — التقييم والخطة — **موجود أصلاً**: `CarePlan` وقايمة
    # المشاكل والقراءات. نسخهم هنا نفس غلطة نسخ الدوا على ورقة الإحالة.
    pending = db.Column(db.Text)
    handed_at = db.Column(db.DateTime)
    handed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: **لمين اتعرضت.** من غير الاسم ده، شاشة «في النص» بتقول إن فيه
    #: مسؤولية معلّقة ومش عارفة تقول مين المفروض ياخدها — يعني بتقول
    #: فيه مشكلة من غير ما تقول مين يحلّها.
    handed_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: (د) **ومين خدها فعلاً.**
    #:
    #: وعمود تاني غير `handed_to_id` عن قصد: ورديّة بتتغيّر، والدكتور
    #: اللي اتعرضت عليه ممكن يبقى مش هو اللي استلم. عمود واحد للاتنين
    #: كان هيخلّي السجل يقول إن اللي اتعرضت عليه هو اللي خدها — وهي
    #: نفس النسبة الغلط اللي `Opinion` و`Referral` بيفرّقوا فيها.
    accepted_at = db.Column(db.DateTime)
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    admission = db.relationship("Admission", backref="responsibilities")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id])
    handed_by = db.relationship("User", foreign_keys=[handed_by_id])
    handed_to = db.relationship("User", foreign_keys=[handed_to_id])
    accepted_by = db.relationship("User", foreign_keys=[accepted_by_id])

    @property
    def live(self):
        """هو المسؤول دلوقتي."""
        return self.until is None

    @property
    def handed_over(self):
        """اتسلّمت **فعلاً** — الطرفين، مش طرف.

        `handed_at` لوحده معناه إن حد قال «أنا مشيت». والمسؤولية ما
        بتمشيش لحد ما حد يقول «أنا خدتها».
        """
        return self.accepted_at is not None and self.accepted_by_id is not None

    @property
    def in_limbo(self):
        """سلّم ومحدّش استلم — **والصف ده بيبان إنه اتسلّم**."""
        return self.handed_at is not None and not self.handed_over

    def __repr__(self):
        return f"<CareResponsibility adm={self.admission_id} live={self.live}>"
