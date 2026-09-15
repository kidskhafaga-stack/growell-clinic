"""الدم: مين طلبه وليه، ومين علّقه، ومين كان قاعد جنب الطفل.

> **ICD.20** The hospital has a process for **requesting** blood and/or blood
> components.
> **ICD.21** Blood and/or blood components are **transfused** according to
> professional practice guidelines.

اتنين معيار، ودورة واحدة — وده السبب في جدولين مش جدول.

**الطلب حدث، والنقل حدث تاني.** الطلب بيتكتب من طبيب في وقت، والنقل بيحصل عند
سرير في وقت تاني وبإيدين تانية، **وطلب ممكن يخلص من غير نقل خالص**: اتلغى،
الحالة اتحسّنت، التوافق فشل. جدول واحد كان هيخلّي «اتطلب» و«اتنقل» نفس الصف،
فطلب ملغي يقرا كأنه دم اتدخل في طفل.

---

**اللي المعياران بيطلبوه في الملف بالنص:**

* `ICD.20` دليل ٣ — *"**Indication** for transfusion is recorded in the
  patient's medical record."*
* `ICD.20` دليل ٤ — البنك بيستلم الدواعي، وحالة الطفل، **وعاجل ولا عادي**.
* `ICD.21` دليل ٣ — *"Blood or blood component bags are **visually checked**
  before transfusion."*
* `ICD.21` دليل ٤ — *"**Monitoring** of the patient's condition during
  transfusion is recorded in the patient's medical record."*

والأربعة دول اللي الجدولين دول موجودين علشانهم. أي حاجة تانية في السياسة —
المعدّل، متى الكيس يترمي، الاعتبارات الخاصة — **سياسة المستشفى**، والبرنامج
بيسجّل اللي اتعمل ومش بيقرّر الأرقام.

---

**ونيّة `ICD.21` كلها جملة واحدة:** *"Wrong blood administration incidents are
mainly due to **human error leading to misidentification of the patient**."*
عشان كده اللي بيعلّق واللي بيراجع اسمين مختلفين على الصف، زي عدّ الشاش
والجراحة بالظبط: توقيع واحد على مراجعة معناه إن اللي عمل الحاجة راجع نفسه.

**والمراقبة مش جدول تالت.** القراءات اللي بتتاخد كل ربع ساعة أثناء النقل هي
`Observation` — نفس الحرارة والنبض والضغط اللي الورديّة بتكتبهم طول اليوم —
فالنقل بيتعلّم عليها بعمود واحد بدل ما البرنامج يبقى فيه مكانين لقراية واحدة.
نفس الحُجّة المكتوبة عن منحنيات التحاليل ودراسات الأجهزة.
"""
from datetime import datetime

from app.extensions import db

#: What was asked for. The hospital's blood bank has its own vocabulary and
#: this is the short list the request form offers — `other` carries whatever
#: it is in the request's own words rather than the program inventing a name.
PRODUCTS = ("whole", "prbc", "platelets", "ffp", "cryo", "other")

#: `ICD.20` (هـ) — *"Clearly communicate whether the blood is **emergently or
#: routinely** needed."* Named in evidence 4 as its own fact, so it is its own
#: column and never inferred from how fast somebody typed.
ROUTINE, EMERGENCY = ("routine", "emergency")
URGENCIES = (ROUTINE, EMERGENCY)

#: Where a request stands. `cancelled` exists because a request that ends in
#: no transfusion is a real and common outcome, and a row that could only be
#: open or transfused would record it as one or the other.
REQUESTED, READY, TRANSFUSED, CANCELLED = ("requested", "ready",
                                           "transfused", "cancelled")
REQUEST_STATES = (REQUESTED, READY, TRANSFUSED, CANCELLED)


class BloodRequest(db.Model):
    """One order for blood — `ICD.20`."""

    __tablename__ = "blood_requests"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The stay or the case it belongs to, when there is one. Both nullable:
    # blood is given in the emergency department to a child nobody has
    # admitted yet, and a request that could only hang off an admission would
    # have no room for the one that matters most.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=True, index=True)

    product = db.Column(db.String(16), nullable=False)
    #: What `other` means, in the requester's words. The program keeps the
    #: clinic's vocabulary and never parses it.
    product_note = db.Column(db.String(120))
    units = db.Column(db.Integer)

    #: **`ICD.20` evidence 3, and the reason this table exists.** *"Recording
    #: the reason for the transfusion **so that the blood bank can check that
    #: the product ordered is suitable for diagnosis**"* — element (د). It is
    #: required, because a request without it is exactly the request the
    #: standard was written about.
    indication = db.Column(db.Text, nullable=False)
    urgency = db.Column(db.String(12), default=ROUTINE, nullable=False)

    state = db.Column(db.String(12), default=REQUESTED, nullable=False,
                      index=True)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    requested_at = db.Column(db.DateTime, default=datetime.utcnow,
                             nullable=False, index=True)

    #: `ICD.20` (ب) — *"Education of patient and family about proposed
    #: transfusion **and recording in the patient's medical record**."*
    #: Three states: an empty box is not a family who was not told.
    family_told = db.Column(db.Boolean)

    #: `ICD.20` (ز) — the qualified member of staff who confirmed the sample's
    #: label matches the form. Its own stamp because it happens in the blood
    #: bank, after the request was written and by somebody else.
    sample_checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    sample_checked_at = db.Column(db.DateTime)

    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))

    patient = db.relationship("Patient", backref="blood_requests")
    admission = db.relationship("Admission", backref="blood_requests")
    requester = db.relationship("User", foreign_keys=[requested_by])
    sample_checker = db.relationship("User", foreign_keys=[sample_checked_by])
    transfusions = db.relationship("Transfusion", back_populates="request",
                                   cascade="all, delete-orphan",
                                   order_by="Transfusion.id")

    @property
    def is_open(self):
        return self.state in (REQUESTED, READY)

    def __repr__(self):
        return f"<BloodRequest {self.product} patient={self.patient_id}>"


class Transfusion(db.Model):
    """One bag, hung and watched — `ICD.21`."""

    __tablename__ = "transfusions"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"),
                           nullable=False, index=True)
    #: Denormalised **on purpose**, and the only copy in these two tables.
    #: Every reader here asks "whose blood is this" and the answer must not
    #: depend on a join staying correct — the identification error in
    #: `ICD.21`'s intent is the one thing this table exists to make visible.
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    #: The bag's own number, as printed on it.
    unit_code = db.Column(db.String(64), index=True)

    #: `ICD.21` evidence 3 — *"Blood or blood component bags are **visually
    #: checked** before transfusion."* Three states, like the operative
    #: report's «or not»: ``None`` nobody said · ``False`` checked and found
    #: wrong · ``True`` checked and sound. A bag found wrong is element (ج) —
    #: *conditions when the bag shall be discarded* — and that is a fact worth
    #: a row, not an absence.
    bag_checked = db.Column(db.Boolean)
    bag_note = db.Column(db.String(200))

    # **Two names, and that is the standard's own point.** *"Wrong blood
    # administration incidents are mainly due to human error leading to
    # misidentification of the patient."* One signature on a double-check
    # means the person who did the thing checked themselves.
    given_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    started_at = db.Column(db.DateTime, index=True)
    finished_at = db.Column(db.DateTime)
    #: Element (د). Free text in the clinic's own units — the program records
    #: the rate somebody set and computes no drip.
    rate = db.Column(db.String(60))

    #: `ICD.21` (و)/(ح) — *"Monitoring and reporting any adverse event"* and
    #: *"Management of transfusion complications"*. ``None`` nobody said ·
    #: ``False`` none occurred · ``True`` one did, and the note carries what
    #: it was and what was done — the same three states and the same reason as
    #: the operative report's complications.
    reaction = db.Column(db.Boolean)
    reaction_note = db.Column(db.Text)
    #: The bag stopped before it finished. Its own fact: a transfusion that
    #: was stopped and one that ran through are not the same record, and
    #: reading it off `finished_at` would make them identical.
    stopped_early = db.Column(db.Boolean, default=False, nullable=False)

    request = db.relationship("BloodRequest", back_populates="transfusions")
    patient = db.relationship("Patient")
    giver = db.relationship("User", foreign_keys=[given_by])
    checker = db.relationship("User", foreign_keys=[checked_by])

    @property
    def is_running(self):
        return self.started_at is not None and self.finished_at is None

    @property
    def two_people_checked(self):
        """Whether two different people put their names to this bag."""
        return (self.given_by is not None and self.checked_by is not None
                and self.given_by != self.checked_by)

    def __repr__(self):
        return f"<Transfusion {self.unit_code} patient={self.patient_id}>"
