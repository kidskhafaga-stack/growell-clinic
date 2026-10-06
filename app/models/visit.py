"""Visit / examination record (Phase 4).

A visit ties together the encounter context, vital signs, diagnoses and the
clinical narrative. Vital growth measurements taken during the visit are also
mirrored into growth_records for the growth charts (Phase 5).
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

VISIT_STATUSES = ["open", "completed"]
# Where an order is. ``collected`` sits between the other two and arrived with
# the lab bench: the sample has been drawn and nobody has run it yet.
#
# **It is a third state, not a second meaning for the first**, and everything
# that used to ask ``status == "requested"`` to mean *no answer yet* has to ask
# ``status != "resulted"`` instead. Four places did — the doctor's results
# inbox, the pending list on the consultation screen, the WhatsApp file
# matcher, and this list — and every one of them would have made an order
# vanish the moment a clinic switched its lab on.
INVESTIGATION_STATUSES = ["requested", "collected", "resulted"]

# The ones still waiting for an answer. The predicate every screen outside the
# lab actually wants: "has this been answered", never "which of the states
# before the answer is it in" — that question belongs to the bench alone.
INVESTIGATION_OPEN = ["requested", "collected"]


class Visit(db.Model):
    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id"), nullable=True
    )

    visit_date = db.Column(db.Date, nullable=False, default=local_today)

    chief_complaint = db.Column(db.Text)
    clinical_exam = db.Column(db.Text)
    plan = db.Column(db.Text)
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), default="open", nullable=False, index=True)
    # Where the encounter happened. A decision taken over WhatsApp is a real
    # consultation and belongs in the child's history like any other — but
    # *which* it was is part of the record, not a detail: a year later,
    # whoever reads the file has to understand why the medicine changed on a
    # day the child never came in.
    channel = db.Column(db.String(12), default="clinic", nullable=False,
                        index=True)              # clinic | whatsapp
    # What the doctor decided, when this visit is a remote follow-up.
    decision = db.Column(db.String(16))          # continue | change | investigate
    # The result it was decided on — so the answer, the decision and the
    # question it came from are one chain rather than three loose rows.
    based_on_id = db.Column(db.Integer,
                            db.ForeignKey("visit_investigations.id"),
                            nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # What the doctor wants the nurse to do — written in the room, read at the
    # station. It was being said out loud across a corridor, which is how an
    # instruction reaches the wrong child or nobody at all.
    nurse_instructions = db.Column(db.Text)

    # Sent to emergency. Recorded rather than remembered: the child leaves the
    # clinic mid-encounter, and the visit that stays behind has to say where
    # they went and why, or it reads as a consultation somebody abandoned.
    # Which specialty panel was on the screen. Recorded rather than derived,
    # because the readings taken belong to the panel that was open — a visit
    # whose doctor later changes specialty must not have its measurements
    # re-labelled underneath it. See app/utils/panels.py.
    specialty_panel = db.Column(db.String(40))

    # **الأعمدة التلاتة دي سجل قديم، مش اللي بيتكتب دلوقتي.**
    #
    # `ACT.14` بيطلب ورقة بتمن بنود وتغذية راجعة، فالإحالة بقى ليها
    # جدول: `Referral`. وهنا مكانش ينفع نحوّلهم — `utils/schema` **مش
    # بيرحّل داتا** (مكتوب في دوكسترينجه: additive only, never rewrites)،
    # وعيادة شغّالة عندها إحالات مكتوبة في الأعمدة دي.
    #
    # فالحل: بطّلنا نكتب فيهم، والقرايات تحت بتسأل الجدول الجديد الأول
    # والعمود القديم بعده. الشاشات القديمة ما اتغيّرتش، والإحالة القديمة
    # لسه بتبان — ومفيش إجابتين لنفس السؤال، لأن **فيه قارئ واحد**.
    referred_at = db.Column(db.DateTime)
    referred_to = db.Column(db.String(120))
    referral_note = db.Column(db.Text)

    # ---- what the family was told on the way out (GAHAR ICD.05 evidence 5) --
    #
    # > *"The plans of care and **follow-up instructions** are recorded in the
    # > patient's medical records."*
    #
    # **Two columns, because «تعالى بعد أسبوعين» and «تعالى فوراً لو سخن» are
    # two different instructions** and only one of them has a date. The second
    # is the safety net — the sentence that sends a child back *before* the
    # appointment when something changes — and a single box holding both would
    # let a booked follow-up stand in for having given one. `ICD.03` (هـ) names
    # *follow-up care instructions* as element (viii) of what a patient leaves
    # the emergency department with, for the same reason.
    #
    # A **date** and not a duration: "in two weeks" is a sentence whose meaning
    # moves every day it is read, and this one is read months later by somebody
    # asking whether the child ever came back.
    followup_due = db.Column(db.Date, index=True)
    followup_instructions = db.Column(db.Text)

    @property
    def referral(self):
        """ورقة `ACT.14` الحيّة بتاعة الزيارة دي، لو فيه."""
        rows = [row for row in (self.referrals or []) if row.live]
        return max(rows, key=lambda r: (r.decided_at, r.id)) if rows else None

    @property
    def is_referred(self):
        return self.referral is not None or self.referred_at is not None

    @property
    def referral_where(self):
        row = self.referral
        return row.sent_to if row is not None else self.referred_to

    @property
    def referral_when(self):
        row = self.referral
        return row.decided_at if row is not None else self.referred_at

    @property
    def referral_why(self):
        row = self.referral
        return row.reason if row is not None else self.referral_note

    patient = db.relationship("Patient", backref="visits")
    doctor = db.relationship("User", backref="visits")
    based_on = db.relationship("VisitInvestigation",
                               foreign_keys=[based_on_id])
    appointment = db.relationship("Appointment", backref="visit", uselist=False)
    vitals = db.relationship(
        "VitalSigns", back_populates="visit", uselist=False,
        cascade="all, delete-orphan",
    )
    diagnoses = db.relationship(
        "Diagnosis", back_populates="visit", cascade="all, delete-orphan",
        order_by="Diagnosis.id",
    )
    # Two foreign keys now run between these tables — the orders raised *in*
    # this visit, and (on a remote follow-up) the one result it was decided
    # *on*. Each relationship has to say which key it means.
    investigations = db.relationship(
        "VisitInvestigation", back_populates="visit",
        foreign_keys="VisitInvestigation.visit_id",
        cascade="all, delete-orphan", order_by="VisitInvestigation.id",
    )
    attachments = db.relationship(
        "PatientAttachment", back_populates="visit",
        order_by="PatientAttachment.id",
    )
    services = db.relationship(
        "VisitService", back_populates="visit",
        cascade="all, delete-orphan", order_by="VisitService.id",
    )
    medications = db.relationship(
        "VisitMedication", back_populates="visit",
        cascade="all, delete-orphan", order_by="VisitMedication.id",
    )
    # Device studies performed in this visit (spirometry, echo, ultrasound…).
    # Kept without cascade: a study is a clinical record of its own and must
    # outlive the visit row it happened in.
    studies = db.relationship(
        "DeviceStudy", back_populates="visit", order_by="DeviceStudy.id",
    )

    @property
    def is_completed(self):
        return self.status == "completed"

    def final_diagnoses(self):
        return [d for d in self.diagnoses if d.dx_type == "final"]

    def labs(self):
        return [x for x in self.investigations if x.kind == "lab"]

    def imaging(self):
        return [x for x in self.investigations if x.kind == "imaging"]

    def __repr__(self):
        return f"<Visit {self.id} p={self.patient_id} {self.visit_date}>"


#: (هـ) الاختيارات بترتيبها على الشاشة. `none` إجابة، مش فراغ: أشعة صدر
#: مالهاش ناحية، وده مختلف عن «محدّش سأل».
SIDES = ("right", "left", "both", "none")


class VisitInvestigation(db.Model):
    """A lab test / imaging study ordered during a visit, with its result.

    Lifecycle: ``requested`` when the doctor orders it, ``resulted`` once the
    result text / comment is entered.
    """
    __tablename__ = "visit_investigations"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"), nullable=True)

    kind = db.Column(db.String(12), default="lab", nullable=False)  # lab | imaging
    name = db.Column(db.String(200), nullable=False)     # Arabic / primary snapshot
    name_en = db.Column(db.String(200))                  # English snapshot (bilingual)
    request_notes = db.Column(db.String(255))

    # ---- `ICD.17` — مين طلب، وليه، وأنهي ناحية ------------------------
    #
    # > Information includes at least: a) Name of the ordering medical staff
    # > member … e) Site and laterality for medical imaging studies.
    # > f) Prompt authentication by the ordering medical staff members.
    #
    # **مين دخّل الطلب**، من اللوج إن مش من فورم — صفر كتابة. قبل كده
    # الطلب كان بيقول «الزيارة بتاعة د. فلان» بس، والزيارة بتاعة دكتور
    # والطلب ممكن تكون ممرضة كتبته بالنيابة عنه. والفرق ده هو (و) بالظبط:
    # طلب اتكتب بلوج الطبيب **متوثّق ساعة ما اتكتب**؛ واللي كتبه غيره
    # مستني توقيعه.
    #
    # فاضي في الصفوف القديمة، **والفراغ ده معناه «محدّش سجّل»** مش «ممرضة
    # كتبته» — فما بيتحسبش ناقص (و). شوف `utils/order_check`.
    ordered_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    #: الطبيب اللي أكّد طلب **مش هو اللي دخّله**. عمودين مش واحد لنفس سبب
    #: `VerbalOrder`: اللي كتب غير اللي وقّع، والسجل لازم يقول الاتنين.
    confirmed_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    confirmed_at = db.Column(db.DateTime)

    #: (هـ) **الناحية — للأشعة.** «أشعة ساعد» من غير «يمين ولا شمال» طلب
    #: بيتنفّذ على الناحية الغلط، وأكتر مكان بيحصل فيه ده إن الورقة
    #: بتروح مركز أشعة بره ومفيش حد يسأله. ومن اختياراتها «مالهاش ناحية»:
    #: أشعة صدر ما لهاش يمين وشمال، والفرق بين «مالهاش» و«محدّش قال» هو
    #: اللي بيخلّي الفراغ يتقري ناقص. **`None` = محدّش قال.**
    laterality = db.Column(db.String(8))

    status = db.Column(db.String(12), default="requested", nullable=False)

    # ---- where it is being done -----------------------------------------
    # **Not a fourth status.** `status` says how far the order has got;
    # this says where it is going, and the two are independent — an order
    # done outside is `requested` until a report comes back and is written
    # on it, exactly like one done here. Putting «outside» inside `status`
    # would have made it a stage of the same pipeline, and `labs.py` already
    # records what a fourth state costs: every screen that asks "has this
    # been answered yet" reads one list, and a new word in it is the
    # difference between a state appearing everywhere and an order vanishing
    # off four screens.
    #
    # Two ways a test ends up here, and they are the same fact:
    #
    # * **the clinic does not do it** — `Investigation.in_house` is off, and
    #   the order is written this way without anybody being asked; and
    # * **the family would rather go elsewhere** — a clinic that has an echo
    #   machine still meets this every day, and it is one press.
    #
    # What it changes is exactly one thing: the bench's own worklist. The
    # order still prints on the prescription, still sits on the child's file,
    # still counts for the pre-operative results SAS.06 asks about, and its
    # result still goes on this same row when the report comes back — see
    # `results_inbox`, which was written for precisely that journey. And it
    # was never going to be billed: `labs.unbilled` reads `collected_at`,
    # *drawn* and not merely ordered.
    #
    # The same shape the vaccines have used since the beginning —
    # `PatientVaccine.given_outside` + `outside_place`, "informational only:
    # no stock deduction, no charge, no doctor fee".
    done_outside = db.Column(db.Boolean, default=False, nullable=False)
    # Where — the lab down the road, a hospital, a scan centre. Asked for the
    # same reason the vaccine asks it: "somewhere else" is only half an
    # answer, and the half that is missing is the one somebody chasing a
    # result two weeks later needs.
    outside_place = db.Column(db.String(160))

    result_text = db.Column(db.Text)        # the doctor's recorded result
    result_comment = db.Column(db.Text)     # the doctor's interpretation

    # **The number, when there is one.**
    #
    # The result has always been Text, which is right for an X-ray report and
    # useless for HbA1c. "Show me this as a curve" is asked for by every
    # specialty in the survey — ferritin, eGFR, INR, IgE, drug levels, eye
    # pressure — and not one of them could be drawn, because you cannot plot
    # prose.
    #
    # Added beside the text rather than instead of it. A culture result and a
    # radiology report are not numbers and never will be; the value is filled
    # where a value exists, and the curve is drawn from the visits that have
    # one.
    result_value = db.Column(db.Float)
    result_unit = db.Column(db.String(20))

    # The reference range **this lab printed on this report**, and that is the
    # whole reason it lives on the result and not in the catalogue.
    #
    # A paediatric range moves with age, and often with the assay the lab
    # happens to run. One range stored centrally and shown for every child
    # would be the program inventing a clinical number — the failure the
    # vaccine tables exist to avoid — so nothing is defaulted here. The doctor
    # copies what the report says, or leaves it blank and the curve simply has
    # no band.
    result_low = db.Column(db.Float)
    result_high = db.Column(db.Float)

    resulted_at = db.Column(db.DateTime)

    # ---- the bench ------------------------------------------------------
    # What happens between the doctor asking and the answer coming back, and
    # what the program had nothing at all for: the order went straight from
    # `requested` to `resulted` because the only hands it passed through were
    # the doctor's, typing what a paper report said.
    #
    # In a hospital there is a step in the middle, and it is the one that goes
    # wrong: **the sample**. A test nobody drew blood for and a test whose
    # blood is sitting in a rack look identical when the only fact stored is
    # "requested" — and the second one is answered by waiting while the first
    # needs somebody to go to the bed.
    sample_code = db.Column(db.String(24), index=True)
    collected_at = db.Column(db.DateTime)
    collected_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    # **The imaging half of the same middle state.** An echo has no tube, so
    # `sample_code` and `collected_at` can never be true of one — and until
    # this existed the only way to move a scan along was to stamp it as a
    # drawn sample, which is a record of something that did not happen.
    #
    # The *status* is shared on purpose: `collected` means "it is under way
    # and nobody has answered yet", which is exactly as true of a scan that
    # has been performed as of a sample that has been drawn. What differs is
    # the event that got it there, and that is what these two carry. See the
    # note above `INVESTIGATION_STATUSES` for why a fourth state would have
    # been the wrong answer.
    performed_at = db.Column(db.DateTime)
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    # Who ran it. Separate from the doctor who reads it: the person who put
    # the number in is the person a query about the number goes to, and on the
    # old flow that was always the doctor because there was nobody else.
    resulted_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    # The line that paid for it, once something has. Same stamp the bed
    # nights, the ward doses and the theatre cases carry: the order knows what
    # charged it, so asking twice charges once.
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                nullable=True, index=True)

    # **The stay this was ordered for, when it was ordered from one.**
    #
    # «ليه مش بتطلب من ملف الإقامة؟» — because an order could only be written
    # at a visit, and a child admitted straight to a bed, or a newborn from
    # delivery, has none. Ordered from the stay, it carries the stay, and the
    # stay's bill is where it is charged — never the outpatient desk, where it
    # used to turn up as if the child had walked in for it.
    #
    # Nullable: every order written before this, and every order written at a
    # clinic visit, belongs to no stay and behaves exactly as it always has.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    # **The case this was ordered for, when it was ordered for one.**
    #
    # GAHAR SAS.06 (هـ) asks that the results of the *required* investigations
    # are there before the child goes in — and the word carrying the weight is
    # **required**. The program must not decide that a tonsillectomy needs a
    # coagulation screen: naming the tests a procedure requires is a clinical
    # judgement and inventing one here is the failure the vaccine tables exist
    # to avoid.
    #
    # So a person says which orders this case waits on, and the program reads
    # the answer off them. Which also rules out the tempting shortcut of
    # reading every outstanding order on the child's file: a ferritin somebody
    # asked for last month would then hold up this morning's appendix.
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=True, index=True)

    # ---- a result written analyte by analyte ---------------------------
    # The values themselves are `LabResultValue` rows (`models/lab_reference`),
    # one per thing measured. These are what a list needs without reading
    # them: a CBC answered as twelve numbers is answered, and a screen that
    # asked `result_value` alone would call it empty.
    #
    # Written only by the lab module's result screen. A clinic's orders never
    # have them, so every screen that reads `analytes_resulted` sees nothing
    # there and behaves exactly as it did.
    analytes_resulted = db.Column(db.Integer)
    #: How many of them fell outside the **approved** range. Drafts never
    #: count: until the laboratory approves a range it flags nothing.
    abnormal_count = db.Column(db.Integer)
    # **A critical value, and whether a doctor has read it.** Stamped when a
    # value beyond the laboratory's critical limit is saved; the doctor who
    # reads it says so, and until then it is on the bell of whoever answers
    # for the child — see `utils/lab_results.critical_waiting`.
    critical_at = db.Column(db.DateTime, index=True)
    critical_seen_at = db.Column(db.DateTime)
    critical_seen_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # The lab's own two acts on a critical value (`utils/lab_critical`):
    # marking a result critical by hand — a positive culture has no number to
    # cross a limit — with the reason; and telling a doctor: who, how, when,
    # by whom, and whether they read it back.
    critical_manual = db.Column(db.String(200))
    critical_called_at = db.Column(db.DateTime)
    critical_called_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    critical_called_to = db.Column(db.String(120))
    critical_call_method = db.Column(db.String(12))
    critical_read_back = db.Column(db.Boolean)
    # ICD.19 (ج-٦): «any difficulties encountered in notifications» — the
    # doctor did not answer, was called three times, was in theatre.
    critical_difficulty = db.Column(db.String(200))
    # **What a scan gave the child** — the dose the machine reported and the
    # contrast that went in (`utils/radiation`). Empty for everything else,
    # and for every scan recorded before this existed.
    dose_kind = db.Column(db.String(10))
    dose_value = db.Column(db.Float)
    # The unit the machine printed it in (`utils/radiation.MEASURES`).
    dose_unit = db.Column(db.String(12))
    contrast_agent = db.Column(db.String(80))
    contrast_route = db.Column(db.String(10))
    contrast_ml = db.Column(db.Float)
    contrast_reaction = db.Column(db.String(10))
    contrast_note = db.Column(db.String(200))
    exposure_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # A device study booked for a day and hour — «بيحتاج حجز ونوم» — and what
    # the family has to do before it. Empty for everything done on the spot.
    booked_for = db.Column(db.DateTime)
    booking_note = db.Column(db.String(160))
    booked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # When this order's consumables left the lab's store (`utils/lab_stock`).
    # Once per order: a result cleared and typed again is the same run.
    consumed_at = db.Column(db.DateTime)
    # ---- urgent, and the lab's door (`utils/lab_reception`) -------------
    # GAHAR DAS.14 (أ) asks the request to carry «special marking for urgent
    # tests», and DAS.22 a STAT time for each test — the catalogue has had
    # the STAT figure for months and no order could say it was STAT, so the
    # figure was never used. ``None`` is «nobody said», read as routine.
    urgent = db.Column(db.Boolean)
    # DAS.15 (ب-١): an accepted specimen is recorded with the date and time
    # it reached the lab and who received it — and (ب-٣) a suboptimal one
    # accepted anyway says why. Empty on every order received before this.
    received_at = db.Column(db.DateTime)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    received_note = db.Column(db.String(200))
    # DAS.20 (ب) and (أ-٨): the result reviewed and released by an authorized
    # member of the laboratory, and who that was. Asked for only where the
    # hospital switches verification on (`utils/lab_release`); a result typed
    # again after it was verified is unverified until somebody looks again.
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # DAS.13 دليل ٥ / DAS.15 (د): a sample drawn here and sent to a referral
    # laboratory — where, when, by whom, on which batch, and when its result
    # came back (`utils/lab_sendout`). Not `done_outside`: that is an order
    # the family takes elsewhere and the bench never touches; this one the
    # lab drew, labelled and shipped, and its result returns to the lab.
    sent_lab_id = db.Column(db.Integer, db.ForeignKey("referral_labs.id"))
    sent_at = db.Column(db.DateTime, index=True)
    # The referral laboratory's price for it when it was sent — its price
    # list at that moment (``ReferralLabPrice``); empty when none was agreed.
    sent_cost = db.Column(db.Float)
    sent_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    sent_batch = db.Column(db.String(24), index=True)
    returned_at = db.Column(db.DateTime)
    # DAS.21 دليل ٢ و٤ / DAS.22 دليل ٣ و٥: a result past its time — the
    # requester told of the delay (whom, when, by whom), and why it was late,
    # which is the investigation the standard asks of every unacceptable
    # turnaround (`utils/lab_tat`).
    delay_told_at = db.Column(db.DateTime)
    delay_told_to = db.Column(db.String(120))
    delay_told_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    delay_reason = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="investigations",
                            foreign_keys=[visit_id])
    collector = db.relationship("User", foreign_keys=[collected_by])
    resulter = db.relationship("User", foreign_keys=[resulted_by])
    invoice_item = db.relationship("InvoiceItem")
    patient = db.relationship("Patient")
    investigation = db.relationship("Investigation")
    orderer = db.relationship("User", foreign_keys=[ordered_by])
    confirmer = db.relationship("User", foreign_keys=[confirmed_by])
    critical_reader = db.relationship("User", foreign_keys=[critical_seen_by])
    critical_caller = db.relationship("User", foreign_keys=[critical_called_by])
    exposure_writer = db.relationship("User", foreign_keys=[exposure_by])
    receiver = db.relationship("User", foreign_keys=[received_by])
    verifier = db.relationship("User", foreign_keys=[verified_by])
    sent_lab = db.relationship("ReferralLab", foreign_keys=[sent_lab_id])
    sender = db.relationship("User", foreign_keys=[sent_by])
    delay_teller = db.relationship("User", foreign_keys=[delay_told_by])
    operation = db.relationship("Operation", backref="investigations",
                                foreign_keys=[operation_id])


    @property
    def has_result(self):
        return bool((self.result_text or "").strip()
                    or (self.result_comment or "").strip()
                    or self.result_value is not None
                    or self.analytes_resulted)

    @property
    def has_number(self):
        """Whether this one can be a point on a curve."""
        return self.result_value is not None

    @property
    def out_of_range(self):
        """Outside the range the report itself gave — or ``None`` if it gave
        none. Three answers, not two: "we were not told" is not "normal"."""
        if self.result_value is None:
            return None
        if self.result_low is None and self.result_high is None:
            return None
        if self.result_low is not None and self.result_value < self.result_low:
            return True
        if self.result_high is not None and self.result_value > self.result_high:
            return True
        return False

    @property
    def result_state(self):
        """Where this order has got to — three states, not two.

        ``requested``  nothing has come back yet;
        ``arrived``    the family sent the film/report, nobody has read it;
        ``resulted``   a doctor read it and wrote what it says.

        The middle one is the one that used to be invisible. An order that
        has been answered but not read is neither "waiting on the patient"
        nor "done", and treating it as the first is how a film sits unread
        while everyone assumes the family never went.
        """
        if self.has_result:
            return "resulted"
        return "arrived" if self.files else "requested"

    @property
    def awaiting_verification(self):
        """A lab result written and not yet released, where the hospital asks
        for release — ``False`` everywhere else (`utils/lab_release`)."""
        from app.utils import lab_release

        return lab_release.awaiting(self)

    @property
    def arrived_at(self):
        """When the first answer to this order reached the clinic."""
        times = [f.created_at for f in (self.files or []) if f.created_at]
        return min(times) if times else None

    def display_name(self, lang="ar"):
        """The English snapshot taken when it was ordered, else the
        catalogue's English name — an order placed before the catalogue had
        one is still named in English on the English screen."""
        if lang == "en":
            if (self.name_en or "").strip():
                return self.name_en
            inv = self.investigation
            if inv is not None and (inv.name_en or "").strip():
                return inv.name_en
        return self.name

    def __repr__(self):
        return f"<VisitInvestigation {self.kind}:{self.name} {self.status}>"


class VisitService(db.Model):
    """A chargeable procedure/service the doctor performs during a visit
    (e.g. echo, nebuliser). It flows into the visit's invoice as a line at the
    doctor's price; the clinical price is resolved at billing time.
    """
    __tablename__ = "visit_services"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)
    # Set once the line lands on an invoice — the "billed" marker that keeps a
    # doctor-added service from being charged twice (same guard vaccines have).
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True)
    name = db.Column(db.String(200), nullable=False)   # snapshot
    quantity = db.Column(db.Integer, default=1, nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="services")
    service = db.relationship("Service")

    def __repr__(self):
        return f"<VisitService visit={self.visit_id} {self.name}>"


class PatientAttachment(db.Model):
    """A file uploaded to a patient's record (e.g. a lab/imaging report)."""
    __tablename__ = "patient_attachments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True, index=True)
    # The order this file answers, when it answers one. A chest film that
    # arrives on WhatsApp belongs *to* the chest film the doctor asked for —
    # filed loose in the documents folder, somebody has to remember it exists.
    investigation_id = db.Column(db.Integer,
                                 db.ForeignKey("visit_investigations.id"),
                                 nullable=True, index=True)

    filename = db.Column(db.String(255), nullable=False)   # stored name on disk
    original_name = db.Column(db.String(255))              # name shown to users
    kind = db.Column(db.String(20), default="report")      # report | result | other
    label = db.Column(db.String(160))
    # How it reached the clinic. "The mother sent it on WhatsApp on Tuesday"
    # is a different fact from "somebody scanned it at the desk", and the
    # doctor reading it wants to know which.
    source = db.Column(db.String(20), default="upload")     # whatsapp | upload
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Who tied this file to an order. NULL while the link is only the
    # program's guess — a guess a doctor should be able to see as a guess.
    linked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    linked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="attachments")
    visit = db.relationship("Visit", back_populates="attachments")
    investigation = db.relationship("VisitInvestigation", backref="files")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])
    linker = db.relationship("User", foreign_keys=[linked_by])

    @property
    def arrived_by_whatsapp(self):
        return self.source == "whatsapp"

    @property
    def link_is_a_guess(self):
        """Linked by the matcher, not by a person who looked at it."""
        return self.investigation_id is not None and self.linked_by is None

    def __repr__(self):
        return f"<PatientAttachment p={self.patient_id} {self.filename}>"


class VisitMedication(db.Model):
    """A medicine the doctor wrote **during the visit**.

    Drugs used to exist only on a prescription, so a doctor who wrote them in
    the room had to type them again to print. They now behave like the visit's
    investigations: recorded in the exam, carried over to the prescription,
    and checked for interactions and paediatric dosing on the spot.
    """
    __tablename__ = "visit_medications"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"), nullable=True)

    name = db.Column(db.String(200), nullable=False)     # snapshot as written
    dose = db.Column(db.String(120))
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    instructions = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="medications")
    patient = db.relationship("Patient")
    drug = db.relationship("Drug")
    generic = db.relationship("GenericDrug")

    def line(self):
        """"Cetal 5 ml · كل 6 ساعات · 3 أيام" — one printable line."""
        parts = [self.name]
        for extra in (self.dose, self.frequency, self.duration):
            if (extra or "").strip():
                parts.append(extra.strip())
        return " · ".join(parts)

    def __repr__(self):
        return f"<VisitMedication {self.name}>"


# «الاجهزة … ممكن تبقى فى عيادة وممكن تجرى فى الاقسام الداخلية» — the first
# device study ordered, from anywhere, opens the device board's door in the
# menu (`utils/device_board.py`). One listener, so no ordering screen has to
# remember.
@db.event.listens_for(VisitInvestigation, "after_insert")
def _device_study_ordered(mapper, connection, target):
    if getattr(target, "kind", None) == "diagnostic":
        from app.utils.device_board import note_on

        note_on(connection)

