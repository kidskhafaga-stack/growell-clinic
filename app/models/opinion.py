"""طلب رأي — استشارة أو رأي تاني. GAHAR `ACT.10` و`ACT.09`.

**وتالت مرة الكتاب بيعدّد نفس القايمة مرتين.** حطّ سياسة المعيارين جنب
بعض:

| | `ACT.09` رأي تاني | `ACT.10` استشارة |
|---|---|---|
| معايير الطلب | (أ) | (أ) |
| توصيل الطلب | (ب) | (ج) |
| مهلة الرد | (د) | (د) |
| تفاصيل الرد | (هـ) | (هـ) |
| **لوحده** | (و) لما المستشفى ما تقدرش تجيبه | (ب) المآل المتوقّع و**العجلة** |

نفس القايمة، والفرق **بندين بالظبط**. فسجل واحد والمطلوب بيتغيّر بالنوع
— زي التخدير والتسكين في `SAS.18`/`SAS.23` بالظبط. وجدولين كانوا هيبقوا
نسختين من نفس الحاجة بيفرقوا مع الوقت.

---

**ونية `ACT.10` بتسمّي أشكال الفشل بالنص، وكل واحد فيهم عمود:**

> a patient and a consultant may be put at a serious disadvantage when
> consultation is requested **late** in the care process, or is **not
> accompanied by sufficient background information**, the **reason for
> consultation is not clearly stated**, or there is a **late response**.

فالسبب مطلوب (مش بيتقبل طلب من غيره)، والخلفية بتتقال ناقصة باسمها،
والرد ليه وقت بيتقاس. **والمهلة إعداد العيادة** — نص المعيار بيقول
*within a **predefined** time frame* — فالبرنامج ما بيخترعش رقم.
"""
from datetime import datetime

from app.extensions import db

CONSULTATION, SECOND_OPINION = ("consultation", "second_opinion")
KINDS = (CONSULTATION, SECOND_OPINION)

#: (ب) في `ACT.10`: «المآل المتوقّع و**العجلة**». التصنيف تشغيلي
#: بكلمتين متعارف عليهم، مش تدرّج إكلينيكي بيحسبه البرنامج.
ROUTINE, URGENT = ("routine", "urgent")
URGENCIES = (ROUTINE, URGENT)

#: اللي القايمتين بيشتركوا فيه.
SHARED = ("reason", "background", "asked_of", "response")
#: و(ب) في الاستشارة لوحدها.
ONLY_CONSULTATION = ("urgency",)
#: و(و) في الرأي التاني لوحده: اللي بيتعمل لما المستشفى ما تقدرش —
#: ودليل ٤ بيقول إن الأهل بيتقالهم على البدايل.
#:
#: **وده البند الوحيد الشرطي في القايمتين.** نصّه بيقول *when the
#: hospital **can't** provide* — فطلب رجع برأي مش ناقصه بديل، والبديل
#: بند اللي ما جاش. `utils.opinions.missing` بتطبّق الشرط ده.
ONLY_SECOND_OPINION = ("alternative",)


def required_for(kind):
    """القايمة المطلوبة للنوع ده — والفرق بندين بالظبط."""
    if kind == CONSULTATION:
        return SHARED + ONLY_CONSULTATION
    return SHARED + ONLY_SECOND_OPINION


class Opinion(db.Model):
    """One request for another professional's view, and the answer."""

    __tablename__ = "opinions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    kind = db.Column(db.String(20), nullable=False, default=CONSULTATION,
                     index=True)

    #: **مطلوب.** النية بتسمّي «السبب مش مكتوب بوضوح» كشكل فشل بالنص،
    #: فالطلب من غيره مرفوض عند الباب.
    reason = db.Column(db.Text, nullable=False)
    #: (ج) في الرأي التاني، و«معلومات كافية» في نية الاستشارة. فاضية
    #: يعني المستشار هيبدأ من الصفر — ودي حاجة الشاشة بتقولها.
    background = db.Column(db.Text)
    #: مين اتطلب منه. تخصص أو اسم — العيادة بتكتب اللي عندها.
    asked_of = db.Column(db.String(120))
    #: (ب) الاستشارة بس.
    urgency = db.Column(db.String(12), index=True)
    #: (و) الرأي التاني بس: اتعمل إيه لما المستشفى ما قدرتش.
    alternative = db.Column(db.Text)

    requested_at = db.Column(db.DateTime, default=datetime.utcnow,
                             nullable=False, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    #: (هـ) تفاصيل الرد — **نص مش علامة**، لأن دليل ٥ بيقول إن تبادل
    #: المعلومات لازم يكون **comprehensive**، وعلامة «اترد عليه» مش
    #: تبادل معلومات.
    response = db.Column(db.Text)
    responded_at = db.Column(db.DateTime, index=True)
    #: **اللي قال الرأي**، لما يكون مستخدم في البرنامج.
    responded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: واسمه لما ما يكونش — استشاري من بره بيرد بورقة أو تليفون.
    responded_by_name = db.Column(db.String(120))
    #: **واللي كتب الرد في البرنامج، وده غير اللي قاله.**
    #:
    #: ممرضة بتكتب رد استشاري من بره مش هي اللي قالت الرأي — وعمود
    #: واحد للاتنين بينسب رأي بره لدكتور جوّه، وده بالظبط نوع النسبة
    #: الغلط اللي `Consent` و`Refusal` بيفرّقوا فيه بين «مين شرح»
    #: و«مين كتب الصف».
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="opinions")
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    responded_by = db.relationship("User", foreign_keys=[responded_by_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])

    @property
    def answered(self):
        """**اترد عليه فعلاً** — الوقت والنص مع بعض.

        وقت من غير نص مش رد: دليل ٥ بيطلب تبادل معلومات، وصف بيقول
        «اترد عليه الساعة تلاتة» ومفيش كلام مش بيجاوب حاجة.
        """
        return (self.responded_at is not None
                and bool((self.response or "").strip()))

    @property
    def waiting_minutes(self):
        """قد إيه استنّى الرد — ولسه مستنّي بتتحسب لدلوقتي."""
        end = self.responded_at or datetime.utcnow()
        return int((end - self.requested_at).total_seconds() // 60)

    def responder_name(self, lang="ar"):
        """مين قال الرأي — **الاسم المكتوب الأول**.

        لأن وجود اسم مكتوب معناه إن اللي رد من بره، واللي داخل بحسابه
        هو اللي بيكتب بس.
        """
        if self.responded_by_name:
            return self.responded_by_name
        if self.responded_by is not None:
            return self.responded_by.display_name(lang)
        return None

    def __repr__(self):
        return f"<Opinion {self.kind} patient={self.patient_id}>"
