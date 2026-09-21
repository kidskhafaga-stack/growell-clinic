"""الإحالة والتحويل بره المستشفى — GAHAR `ACT.14`.

النية بتقول الدايرة بالنص:

> **Recording and responding to referral feedback** ensures continuity of
> care and **completes the cycle of referral**.

**والبرنامج كان عارف نص الدايرة.** `Visit.referred_at/_to/referral_note`
موجودين من زمان، وبيتكتبوا بزرار، وبيبانوا على أربع شاشات. يعني الورقة
بتمشي. اللي مكانش موجود إن حد يقفل الدايرة: **راحت، ورجع منها إيه؟**

---

**وإحالة وتحويل مش نفس الحاجة، والنية بتفرّق بينهم:**

> A **referral** is when the patient leaves the hospital to seek additional
> medical care **temporarily** in another organization.
>
> A **transfer** is when the patient **leaves** the hospital and gets
> transferred to another organization.

نفس الورقة بنفس البنود من (i) لـ(viii) — فجدول واحد بعمود نوع، زي
`Abbreviation` بالظبط. **والفرق اللي بيفرق:** التغذية الراجعة بتخص
**الإحالة**، لأن الطفل راجع. التحويل الطفل مشي فيه خلاص، والانتظار
لرد على تحويل بيملا القايمة بصفوف عمرها ما هتتقفل.

---

**وبندين من التمانية مش هنا عن قصد:**

> iii) Collected information through **assessments and care**.
> iv) **Medications** and provided treatments.

دول في الزيارة والروشتة أصلاً. نسخهم هنا معناه إجابتين لنفس السؤال —
ونسخة بتقدم من ساعة ما الروشتة تتعدّل. الورقة بتتجمّع وقت الطبع من
مصدرها، زي `utils/transfer.py` بيعمل للوليد بالظبط.
"""
from datetime import datetime

from app.extensions import db

#: النوعين اللي النية بتسمّيهم. نفس الورقة، والفرق إن الطفل راجع ولا لأ.
REFERRAL, TRANSFER = ("referral", "transfer")
KINDS = (REFERRAL, TRANSFER)


class Referral(db.Model):
    """ورقة إحالة أو تحويل واحدة — واللي رجع منها."""

    __tablename__ = "referrals"

    id = db.Column(db.Integer, primary_key=True)
    #: (i) تعريف المريض — بالصف نفسه، مش باسم متكتوب بإيد.
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: الزيارة اللي مشي منها. فاضية لو الإحالة من إقامة.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    kind = db.Column(db.String(12), nullable=False, default=REFERRAL,
                     index=True)

    #: (ii) **السبب — مطلوب.** ورقة رايحة لمستشفى تانية من غير سبب هي
    #: طفل بيوصل لحد ما يعرف ليه جه.
    reason = db.Column(db.Text, nullable=False)
    #: (vii) الجهة.
    sent_to = db.Column(db.String(120))

    #: (v) **عمودين مش واحد.** «راح بإسعاف» و«محتاج أكسچين في الطريق»
    #: حقيقتين مختلفتين، وخانة واحدة بتخلّي الأولى تنوب عن التانية —
    #: ونقل من غير المراقبة المطلوبة هو الحتة اللي بتوقع في الطريق.
    transport = db.Column(db.String(120))
    monitoring = db.Column(db.Text)
    #: (vi) حالته وهو ماشي. دي اللي المستقبِل بيقارن بيها لما يوصل.
    condition = db.Column(db.Text)

    #: (viii) **اللي قرّر** — في السجل، مش في سجل النشاط.
    #:
    #: `ActivityLog` بيقول مين ضغط الزرار، وده أثر تدقيق. والمعيار
    #: بيطلب الاسم يكون **على الورقة**: اللي بيستقبل الطفل بيقرا الورقة،
    #: وما بيفتحش لوج البرنامج.
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)

    # ---- دليل ٥: التغذية الراجعة — «تتراجع، وتتوقّع، وتتسجّل» --------
    #
    # **تلات أفعال جنب بعض في نص المعيار**، *reviewed, **signed**, and
    # recorded* — ودول مش فعل واحد بتلات أسماء:
    #
    # الأهل بيسلّموا الورقة للاستقبال، والاستقبال بيحطّها في الملف
    # (**recorded**). واللي لازم يقراها ويقرّر هو الطبيب
    # (**reviewed, signed**) — وده ممكن يبقى بعدها بيومين.
    #
    # **فاللي كتب غير اللي وقّع**, زي `Opinion` بالظبط. وعمود واحد
    # للاتنين كان هيخلّي ورقة اتسلّمت لموظف استقبال تبان زي ورقة دكتور
    # راجعها وبنى عليها — وهي أوحش نوع نقص، لأنها **بتبان مكتملة**.
    feedback = db.Column(db.Text)
    feedback_at = db.Column(db.DateTime, index=True)
    #: مين حطّها في الملف.
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: ومين راجعها ووقّع — وده اللي دليل ٥ بيطلبه بالاسم.
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)

    #: الإلغاء اللي كان موجود كزرار تراجع. **مش مسح**: إحالة اتكتبت على
    #: الطفل الغلط حاجة بتحصل في نفس الدقايق دي، والصف بيفضل علشان
    #: يفضل مقروء.
    cancelled_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="referrals")
    visit = db.relationship("Visit", backref="referrals")
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])

    @property
    def live(self):
        return self.cancelled_at is None

    @property
    def answered(self):
        """**رجع رد فعلاً** — الوقت والنص مع بعض.

        وقت من غير كلام مش رد، زي `Opinion.answered` بالظبط: دليل ٥
        بيقول *recorded*، وصف بيقول «رد يوم الخميس» ومفيش كلام مش
        استمرارية رعاية.
        """
        return (self.feedback_at is not None
                and bool((self.feedback or "").strip()))

    @property
    def signed(self):
        """**واتوقّع** — ودي الحتة التالتة اللي دليل ٥ بيطلبها لوحدها.

        رد وصل ومحدّش راجعه هو ورقة في الملف، مش قرار. والمعيار كاتب
        التلاتة جنب بعض: *reviewed, **signed**, and recorded*.
        """
        return self.reviewed_at is not None and self.reviewed_by_id is not None

    @property
    def closed(self):
        """الدايرة اتقفلت: رد رجع، وحد راجعه ووقّع عليه."""
        return self.answered and self.signed

    @property
    def waiting_days(self):
        """قد إيه بقالها ماشية من غير رد — ولسه مستنية بتتحسب لدلوقتي.

        **بالأيام مش بالدقايق** (عكس `Opinion`): الاستشارة جوّه المستشفى
        بتترد في نفس اليوم، والورقة اللي راحت لمستشفى تانية بترجع بعد
        زيارة الطفل ليها — والدقيقة هنا دقة مالهاش معنى.
        """
        end = self.feedback_at or datetime.utcnow()
        return int((end - self.decided_at).total_seconds() // 86400)

    def __repr__(self):
        return f"<Referral {self.kind} → {self.sent_to}>"
