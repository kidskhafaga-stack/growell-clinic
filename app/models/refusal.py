"""رفض مستنير — GAHAR `PCC.10`.

المعيار مش بيسأل «الأهل رفضوا؟» — البرنامج عارف ده خلاص: `self_discharge`
موجودة في مآلات الطوارئ وفي مخارج الإقامة من زمان. بيسأل حاجة تانية خالص:
**حد قالهم إيه اللي ممكن يحصل؟**

والسياسة بتعدّد أربع حاجات، وكل واحدة فيهم سؤال لوحده:

> a) How to inform the patient/family of the patient's **current medical
>    condition**.
> b) How to inform the patient/family of the **consequences** of their
>    decision.
> c) How to **record** patient and/or family refusal of the medical care
>    process step.
> d) Patients are informed about available care and treatment
>    **alternatives**.

ودليل ٢ بيقول إن الاستمارة لازم تحتوي **الأربعة** — *"contains all required
information regarding the intent from a) through d)"*. يعني علامة واحدة
اسمها «رفضوا وعارفين» مش استمارة، دي جملة.

---

**والفرق بين «رفض» و«رفض مستنير» هو دول بالظبط.** طفل خرج والأهل ما
اتقالّهمش إيه اللي ممكن يحصل — ده مش رفض مستنير، ده خروج. والبرنامج كان
بيسجّل التاني وبيسمّيه الأول.

**وليه مش عمود على `Consent`؟** لأن اللي المعيارين بيطلبوهم مختلفين:
الموافقة `PCC.08` عايزة توقيع الطبيب اللي شرح، والرفض `PCC.10` عايز
**العواقب والبدايل** — وحاجة من دول مش في التانية. جدول واحد بعلامة
«موافق/رافض» كان هيخلّي نص الأعمدة فاضية على طول في كل صف.

---

**وفي طب الأطفال، اللي بيرفض مش المريض.** الطفل قاصر، فالرفض من الوصي —
ودليل ٤ بيقول إن ده لازم يمشي مع القانون. فاسمه وصلته ورقمه بيتكتبوا،
زي ما بيحصل في `Consent` بالظبط.
"""
from datetime import datetime

from app.extensions import db

#: النية بتسمّي التلاتة بالنص: رفض خطوة (AMA) · خروج من الإقامة ضد
#: النصيحة (DAMA) · سيبان الطوارئ (LAMA). تلاتة مش واحدة، لأن اللي
#: بيتقال للأهل بيختلف: «الجرعة دي» غير «هيخرج النهاردة» غير «ماشي من
#: غير ما حد يشوفه».
STEP, DISCHARGE, EMERGENCY = ("step", "discharge", "emergency")
KINDS = (STEP, DISCHARGE, EMERGENCY)

#: الأربعة اللي دليل ٢ بيطلب إن الاستمارة تحتويهم كلهم.
ELEMENTS = ("condition", "consequences", "refused", "alternatives")


class Refusal(db.Model):
    """One informed refusal, and the four things that make it informed."""

    __tablename__ = "refusals"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    emergency_visit_id = db.Column(db.Integer,
                                   db.ForeignKey("emergency_visits.id"),
                                   nullable=True, index=True)
    kind = db.Column(db.String(16), nullable=False, default=STEP, index=True)

    # --- الأربعة، وكل واحدة عمود لأنها سؤال لوحده ---
    #: (أ) حالته دلوقتي زي ما اتقالت لهم. بكلام اللي شرح — البرنامج مالوش
    #: قايمة حالات ولا بيترجم اللي اتقال.
    condition = db.Column(db.Text)
    #: (ب) إيه اللي ممكن يحصل لو مشيوا في قرارهم. **ودي أهم واحدة**،
    #: لأنها اللي بتفرّق بين رفض مستنير ورفض.
    consequences = db.Column(db.Text)
    #: (ج) بيرفضوا إيه بالظبط. «رفضوا العلاج» مش بند — أنهي خطوة.
    refused = db.Column(db.Text)
    #: (د) البدايل اللي اتعرضت عليهم. ومفيش بدايل حاجة تتكتب، مش خانة
    #: تتساب فاضية: «مفيش بديل» إجابة، و«محدّش سأل» إجابة تانية.
    alternatives = db.Column(db.Text)

    # --- مين رفض. في طب الأطفال: الوصي، مش الطفل (دليل ٤) ---
    guardian_name = db.Column(db.String(120))
    guardian_relation = db.Column(db.String(20))
    guardian_id_no = db.Column(db.String(20))

    # --- والدليل إنهم شافوها فعلاً. نفس شكل `Consent` بالظبط، لأنه نفس
    #     السؤال: ورقة فيها اسم من غير حاجة تانية دعوى مش مستند.
    signature_file = db.Column(db.String(255))
    signature_kind = db.Column(db.String(10))          # paper | drawn
    signature_at = db.Column(db.DateTime)

    #: الطبيب اللي شرح. غير `recorded_by` — ده الحساب اللي كتب الصف.
    explained_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="refusals")
    explained_by = db.relationship("User", foreign_keys=[explained_by_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])

    @property
    def has_signature(self):
        return bool(self.signature_file)

    @property
    def informed(self):
        """الأربعة اتكتبوا. **مش «فيه استمارة»** — دليل ٢ بيطلب المحتوى."""
        return all((getattr(self, name) or "").strip() for name in ELEMENTS)

    def __repr__(self):
        return f"<Refusal {self.kind} patient={self.patient_id}>"
