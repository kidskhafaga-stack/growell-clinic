"""إنعاش قلبي رئوي واحد، من ساعة ما اتعرف لحد ما خلص — GAHAR `CSS.05`.

دليل ٦ بيقول بالنص: *"Management of cardio-pulmonary arrests is **recorded in
the patient's medical record**"*. والسياسة (أ)–(ط) أغلبها إعداد وتدريب، بس
تلات بنود منها بيتثبتوا في الملف:

> (e) Mechanisms for **calling** staff members to respond …
> (f) The **time frame** of response.
> (h) **Recording** of response and management.

---

**وفيه رقم في المعيار نفسه، والبرنامج بيقراه ومش بيخترعه.** دليل ٣ بالنص:

> Staff with basic life support start the process **immediately**, while those
> with advanced life support will start **within a maximum of 5 minutes**.

دي مش عتبة إكلينيكية المستشفى بتحطّها — دي رقم مكتوب في الكتاب، فالبرنامج
بيقيس عليه وبيقول «الاستجابة المتقدّمة عدّت الخمس دقايق». وده الاستثناء
الوحيد لقاعدة «البرنامج ما بيخترعش رقم»، ومكتوب هنا علشان يفضل استثناء.

**وتلات أوقات مش وقت واحد**، وده السبب اللي ثلاثتهم أعمدة: اللحظة اللي حد
شاف فيها إن الطفل واقف · اللحظة اللي الاستغاثة اتبعتت فيها · واللحظة اللي
الفريق وصل فيها. فرق أي اتنين فيهم رقم مختلف بيقول حاجة مختلفة، وعمود واحد
كان هيخلّي «تأخير النداء» و«تأخير الوصول» نفس الحاجة.
"""
from datetime import datetime

from app.extensions import db

#: الرقم من الكتاب، مش من عندنا — `CSS.05` دليل ٣.
ALS_MINUTES = 5

#: النتيجة. تصنيف تشغيلي بأسماء متعارف عليها، مش تدرّج إكلينيكي.
ROSC, DIED, TRANSFERRED = ("rosc", "died", "transferred")
OUTCOMES = (ROSC, DIED, TRANSFERRED)


class Resuscitation(db.Model):
    """One cardio-pulmonary arrest and the response to it."""

    __tablename__ = "resuscitations"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    # فين حصل. بيتكتب بكلام المستشفى لأن المستشفى هي اللي بتسمّي أماكنها،
    # والمكان بيهمّ: نداء من الأشعة غير نداء من سرير جنب محطة التمريض.
    place = db.Column(db.String(120))

    # --- التلات أوقات ---
    recognised_at = db.Column(db.DateTime, default=datetime.utcnow,
                              nullable=False, index=True)
    called_at = db.Column(db.DateTime)           # (هـ) الاستغاثة اتبعتت
    team_at = db.Column(db.DateTime)             # (و) الفريق وصل

    # (ح) اللي اتعمل. بكلام اللي كتب — البرنامج مالوش بروتوكول إنعاش،
    # والمستشفى ليها سياستها وفريقها.
    management = db.Column(db.Text)
    started_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    team_lead_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    ended_at = db.Column(db.DateTime, index=True)
    outcome = db.Column(db.String(16), index=True)

    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="resuscitations")
    started_by = db.relationship("User", foreign_keys=[started_by_id])
    team_lead = db.relationship("User", foreign_keys=[team_lead_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])

    @property
    def is_running(self):
        return self.ended_at is None

    @property
    def to_call(self):
        """من ساعة ما اتعرف لحد ما الاستغاثة اتبعتت، بالدقايق."""
        if self.called_at is None:
            return None
        return int((self.called_at - self.recognised_at).total_seconds() // 60)

    @property
    def to_team(self):
        """من ساعة ما اتعرف لحد ما الفريق وصل، بالدقايق."""
        if self.team_at is None:
            return None
        return int((self.team_at - self.recognised_at).total_seconds() // 60)

    @property
    def late_team(self):
        """الفريق المتقدّم عدّى الخمس دقايق؟ ``None`` لو لسه ما وصلش.

        **الرقم من الكتاب مش من عندنا** — `CSS.05` دليل ٣. ولسه ما وصلش
        مش «في الميعاد»: دي حالة تالتة، والخلط بينها وبين «وصل بدري»
        بيخلّي إنعاش الفريق ما وصلوش فيه خالص يبان سليم.
        """
        minutes = self.to_team
        return None if minutes is None else minutes > ALS_MINUTES

    @property
    def minutes(self):
        end = self.ended_at or datetime.utcnow()
        return int((end - self.recognised_at).total_seconds() // 60)

    def __repr__(self):
        return f"<Resuscitation patient={self.patient_id} {self.recognised_at}>"
