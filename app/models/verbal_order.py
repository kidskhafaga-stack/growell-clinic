"""أمر شفهي أو تليفوني، من ساعة ما اتقال لحد ما اللي قاله أكّده — `ICD.18`.

النية بتقول السبب بالنص:

> Miscommunication is the **commonest root cause** for adverse events. Writing
> down and reading back the complete order, by the person receiving the
> information, minimizes miscommunication …

والسياسة (ب)–(د) **تلات حاجات مختلفة بيحصلوا واحدة ورا التانية**:

> b) Verbal orders and telephone orders are **documented** by the receiver.
> c) Verbal orders and telephone orders are **read back** by the receiver.
> d) **Confirmed** by the ordering physician.

**وعلامة واحدة بتقف مكان التلاتة هي بالظبط اللي المعيار موجود علشانه.**
اللي بيكتب الأمر بيعمل (ب) على طول — هو كاتبه. و(ج) حاجة تانية خالص: إنه
يقراه بصوت عالي واللي قاله يسمعه. و(د) حاجة تالتة: اللي قال الأمر يرجع
يقول «أيوه ده اللي قلته». علامة واحدة اسمها «اتحقّق منه» بتخلّي التلاتة
واحدة، وبكده الأمر اللي اتكتب غلط واتأكّد من اللي كتبه غلط يبان سليم.

فتلات أوقات، وتلات أعمدة.

---

**واللي أكّد لازم يكون غير اللي كتب.** (د) بتقول *the ordering physician* —
واللي استلم الأمر بيأكّد كتابته هو نفسه مش تأكيد، ده بالظبط اللي القراية
بصوت عالي موجودة علشان تمسكه. فالسجل بيرفض.

**والمهلة إعداد العيادة.** دليل ٤ بيقول *"within a **predefined**
timeframe"* — يعني المستشفى هي اللي بتعرّفها، والبرنامج ما بيخترعش رقم.
وطول ما هي فاضية مفيش أمر بيتقال عليه إنه اتأخر.

**ووقت الكلام غير وقت الكتابة.** المهلة بتتقاس بين الاتنين، وعمود واحد
كان هيخلّي قياسها مستحيل — والأمر اللي اتقال الساعة تلاتة واتكتب الساعة
تسعة يبان مكتوب في وقته.
"""
from datetime import datetime

from app.extensions import db

#: (أ) «إمتى ينفع يتستعملوا» — والسياسة بتفرّق بينهم، فالسجل بيفرّق.
#: نداء من جنب السرير غير مكالمة تليفون: التاني محدّش شايف اللي بيكتب.
SPOKEN, PHONE = ("spoken", "phone")
CHANNELS = (SPOKEN, PHONE)


class VerbalOrder(db.Model):
    """One verbal or telephone order and the three things that must happen."""

    __tablename__ = "verbal_orders"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    channel = db.Column(db.String(16), nullable=False, default=SPOKEN,
                        index=True)

    # نص الأمر بكلام اللي استلمه. البرنامج مالوش قايمة أوامر ولا بيترجم
    # اللي اتقال — و«الأمر الكامل» في النية معناها اللي اتقال بالظبط.
    text = db.Column(db.Text, nullable=False)

    # --- التلات حاجات، وكل واحدة وقتها ---
    #: (ب) اتكتب. ودي بتحصل ساعة ما الصف ده يتعمل، فمالهاش خانة تتساب
    #: فاضية: الصف نفسه هو الكتابة.
    written_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    #: (ج) اتقرا بصوت عالي واللي قاله سمعه.
    read_back_at = db.Column(db.DateTime, index=True)
    #: (د) اللي قال الأمر أكّده.
    confirmed_at = db.Column(db.DateTime, index=True)

    #: إمتى اتقال — مش إمتى اتكتب. والفرق هو اللي المهلة بتقيسه.
    spoken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                          index=True)

    #: اللي قال الأمر، واللي استلمه. اتنين مختلفين بالضرورة.
    ordered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              index=True)
    received_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                               index=True)
    #: و(هـ) «متطلبات التوثيق والتصديق» — مين أكّد، مش بس إنه اتأكّد.
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    #: اسم اللي قال الأمر لما ما يكونش مستخدم في البرنامج — استشاري من
    #: بره بيتصل بالليل موجود، وسطر فاضي مكانه بيخلّي الأمر مجهول المصدر.
    ordered_by_name = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="verbal_orders")
    ordered_by = db.relationship("User", foreign_keys=[ordered_by_id])
    received_by = db.relationship("User", foreign_keys=[received_by_id])
    confirmed_by = db.relationship("User", foreign_keys=[confirmed_by_id])

    @property
    def read_back(self):
        return self.read_back_at is not None

    @property
    def confirmed(self):
        return self.confirmed_at is not None

    @property
    def closed(self):
        """التلاتة تمّوا. **مش «اتأكّد»** — التأكيد واحد منهم مش كلهم."""
        return self.read_back_at is not None and self.confirmed_at is not None

    @property
    def delay_minutes(self):
        """من ساعة ما اتقال لحد ما اتكتب، بالدقايق.

        ودي اللي دليل ٤ بيتكلم عنها. ``None`` مستحيلة هنا لأن العمودين
        مطلوبين — بس الحساب مكتوب مرة واحدة علشان الشاشة والقاري يقولوا
        نفس الرقم.
        """
        return int((self.written_at - self.spoken_at).total_seconds() // 60)

    def ordering_name(self, lang="ar"):
        """اللي قال الأمر — مستخدم كان ولا اسم مكتوب.

        **دالة مش خاصية** علشان تاخد اللغة: اسم المستخدم ليه نسخة بكل
        لغة، والصفحة اللي بتقرا العمود الخام على طول بتخلط اللغتين في
        سطر واحد.
        """
        if self.ordered_by is not None:
            return self.ordered_by.display_name(lang)
        return self.ordered_by_name or None

    def __repr__(self):
        return f"<VerbalOrder patient={self.patient_id} {self.spoken_at}>"
