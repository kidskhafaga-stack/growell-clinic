"""الاختصارات الموحّدة — GAHAR `IMT.04`.

النية بتقول الخطر بالنص:

> codes, symbols, and abbreviations are used to **squeeze a lot of writing
> into a small space**. This may cause **miscommunication** between
> healthcare professionals and potential **errors in patient care**.

**والبرنامج ده عنده نص الحل من زمان.** `utils/rx_shorthand` بيحوّل
«q8h» لـ«كل ٨ ساعات» وهي بتتكتب، و`utils/phrases` بيحوّل كود الدكتور
لجملة كاملة. الاتنين شغلهم إن اللي بيتخزّن في الملف يبقى **الكلام
الطويل** مش الاختصار. فاللي ناقص مش منع الاختصارات — ده **قايمتين
وفاحص**، وده اللي دليل ٤ بيطلبه: *"Violation of the list of not-to-use
symbols/abbreviations is **monitored**"*.

---

**وقايمة واحدة بعمودين، مش جدولين.** (أ) مسموح و(ب) ممنوع — والاتنين
نفس الشكل بالظبط: رمز، ومعناه، وملاحظة. الفرق بينهم كلمة واحدة، فجدولين
كانوا هيبقوا نسختين بيفرقوا مع الوقت.

**والقايمتين بيبدأوا فاضيين.** (ب) بيقول إن القايمة الممنوعة *"guided by
reliable references, **such as** the ISMP list"* — يعني بيشاور على مرجع
**بره الكتاب**. ورقم الخمس دقايق في `CSS.05` كان مكتوب في نص المعيار
فالبرنامج قراه؛ ودي لأ. وكمان (ج) بيتكلم عن **الاختصارات غير
الإنجليزية** بالنص، وقايمة ISMP كلها إنجليزي — فعيادة بتكتب بالعربي
محتاجة قايمتها هي.
"""
from datetime import datetime

from app.extensions import db

#: (أ) و(ب) — نفس الشكل، والفرق كلمة.
APPROVED, BANNED = ("approved", "banned")
KINDS = (APPROVED, BANNED)

#: (د) المواقف اللي **حتى المسموح** ممنوع فيها:
#:
#: > Situations where symbols and abbreviations (**even the approved list**)
#: > must not be used, such as **informed consent** and any record that
#: > **patients and families receive** from the hospital.
#:
#: فالفاحص بياخد **سياق** مش نص بس: نفس الاختصار مقبول في ملاحظة وممنوع
#: في موافقة. وده الفرق اللي لو مش موجود، الفحص يا بيبقى مفرط في السماح
#: على الورق اللي بيروح للأهل، يا بيبقى مفرط في المنع جوّه الملف.
NOTE, FAMILY = ("note", "family")
CONTEXTS = (NOTE, FAMILY)


class Abbreviation(db.Model):
    """One symbol or abbreviation the clinic has ruled on."""

    __tablename__ = "abbreviations"
    __table_args__ = (
        db.UniqueConstraint("text", name="uq_abbreviation_text"),
    )

    id = db.Column(db.Integer, primary_key=True)
    #: الرمز زي ما بيتكتب. **حسّاس للحالة عن قصد**: «MS» اختصار ممنوع،
    #: و«ms» جزء من كلمات كتير — والفاحص بيفرّق بينهم.
    text = db.Column(db.String(40), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default=BANNED,
                     index=True)
    #: معناه، أو اللي المفروض يتكتب بدله. ودي اللي بتخلّي رسالة الفاحص
    #: مفيدة: «اكتب units» أحسن من «فيه اختصار ممنوع».
    means = db.Column(db.String(120))
    note = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    @property
    def banned(self):
        return self.kind == BANNED

    def __repr__(self):
        return f"<Abbreviation {self.text} {self.kind}>"
