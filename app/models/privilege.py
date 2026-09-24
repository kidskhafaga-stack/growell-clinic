"""What a doctor is authorised to do here — and nowhere else.

GAHAR WFM.12 defines it, and the definition is the whole reason this is a
record rather than a rule:

> Clinical privilege refers to the **specific authorization or permission
> granted** to a healthcare provider ... **by a healthcare institution**.

> Clinical privileges are **specific to the healthcare institution** where they
> are granted and **may vary from one institution to another** based on the
> institution's needs, the provider's qualifications, and the services offered.

So the program holds no opinion about who may do what. It does not know that a
paediatric surgeon may do a herniotomy; it knows that **this hospital wrote it
down**, when, until when, and who signed. Every other reading would be the
program inventing a credentialing decision — the one thing this codebase
refuses to do with clinical judgement.

And SAS.02 (أ) is what makes it more than a filing cabinet: *"Surgeries and
invasive procedures are booked according to granted clinical privileges"*, with
WFM.12's fourth item of evidence naming the place it has to show up —
*"Clinical privileges are **accessible to and used by staff involved in
booking**"*.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_date

#: The kinds WFM.12 names, in its own words. The first is the ordinary one;
#: the other three are quoted from the standard and each **ends differently**,
#: which is the reason they are not one word with a date on it:
#:
#: * ``temporary`` — *"provisional authorization ... for a limited period **not
#:   exceeding 90 days**, for example, during the probationary period"*
#: * ``emergency`` — *"immediate, time-limited authorization ... granted for a
#:   very short duration of an emergency and is **valid only until the
#:   immediate crisis is over**"*
#: * ``disaster`` — *"during a **declared disaster** or public health
#:   emergency ... valid until the emergency period concludes"*
#:
#: An emergency privilege with an expiry date three months out is not an
#: emergency privilege, and a screen that could not tell them apart would let
#: one become the other by nobody doing anything.
PRIVILEGE_KINDS = ("standard", "temporary", "emergency", "disaster")

#: *"When medical staff are granted a privilege under supervision, clinical
#: privileges address the accountable supervisors"* (WFM.12 g). Held as a
#: named person, because "supervised" without a supervisor is the box this
#: whole module exists to replace.
SUPERVISED = "supervised"

#: The handbook's own maximum review interval — *"reviewed and renewed **at
#: least every three years**"* (WFM.12 d). Quoted so the screen can say it.
#: **Nothing computes from it.** Each privilege carries the date this hospital
#: set, and a date the program guessed would be a renewal nobody scheduled.
MAX_REVIEW_YEARS = 3


class ClinicalPrivilege(db.Model):
    """One thing one doctor is authorised to do here.

    **Two shapes of scope, and a clinic needs both.** A delineation form reads
    "general surgery: all of it, plus these four named procedures" — so a row
    names *either* a service type (everything of that kind) *or* one service.
    Making it services only would have somebody tick forty boxes per surgeon,
    which is how a privileges list stops being maintained; making it types only
    would lose the named exception, which is usually the interesting one.

    **Withdrawn, never deleted** — the same rule the consent follows. A case
    booked last March under a privilege that stood then must go on reading as
    correct, and a row that can vanish takes that history with it.
    """
    __tablename__ = "clinical_privileges"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)

    #: Exactly one of these three. ``service_type`` is a key from the clinic's
    #: own catalogue; ``service_id`` is one named procedure.
    service_type = db.Column(db.String(20), index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), index=True)
    #: **The anaesthetist's scope** (SAS.16, evidence 3): *"Anesthesia and
    #: sedation are administered by qualified physicians **according to their
    #: approved clinical privileges**"*. An anaesthetist is privileged for a
    #: kind of anaesthetic — general, regional, sedation — not for a hernia,
    #: so the scope is one of :data:`app.models.theatre.ANAESTHESIA_TYPES`.
    #: A procedure scope could not say it: the same child's hernia is a
    #: general anaesthetic in one room and a caudal in the next.
    anaesthesia_kind = db.Column(db.String(12), index=True)

    kind = db.Column(db.String(12), default="standard", nullable=False)
    #: WFM.12 (g): the accountable supervisor, the mode and the frequency.
    #: A supervised privilege with nobody named is not one.
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    supervision = db.Column(db.String(160))

    valid_from = db.Column(db.Date)
    #: When this hospital says it must be looked at again. Set by them, never
    #: computed here — see :data:`MAX_REVIEW_YEARS`.
    valid_until = db.Column(db.Date)

    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(200))

    withdrawn_at = db.Column(db.DateTime)
    withdrawn_reason = db.Column(db.String(200))

    doctor = db.relationship("User", foreign_keys=[doctor_id])
    supervisor = db.relationship("User", foreign_keys=[supervisor_id])
    granter = db.relationship("User", foreign_keys=[granted_by])
    service = db.relationship("Service")

    @property
    def is_supervised(self):
        """Under supervision, and with somebody accountable named.

        A row saying "supervised" with no supervisor is exactly the empty tick
        this module replaces, so it does not count as supervision — it reads as
        an ordinary privilege and the screen shows the gap.
        """
        return self.supervisor_id is not None

    def stands_on(self, day):
        """Was this privilege in force on ``day``?

        **Judged against the day asked about, never against today** — the same
        rule the consent follows, and for the same reason: a case booked last
        March under a privilege that stood then must go on reading as correct
        after the privilege lapses or is withdrawn.

        ``valid_from`` and ``valid_until`` are ``Date`` columns a person typed,
        so they are already the clinic's dates and compare directly. **The
        withdrawal is not**: ``withdrawn_at`` is a UTC ``DateTime``, and
        ``.date()`` on it is the *UTC* day.

        For any clinic ahead of UTC that is wrong for two or three hours every
        night. Cairo is UTC+2: a privilege withdrawn at half past midnight
        local is stamped 22:30 the previous day in UTC, and a case booked the
        day before then read as **outside the surgeon's privileges** — the
        program retroactively saying somebody was not allowed to do an
        operation they were allowed to do. Found by a CI run that happened to
        cross local midnight.

        So the stamp is read through the clinic's clock, like every other
        stored moment this program compares against a date somebody typed.
        """
        if day is None:
            return False
        if self.valid_from and day < self.valid_from:
            return False
        if self.valid_until and day > self.valid_until:
            return False
        if self.withdrawn_at and local_date(self.withdrawn_at) <= day:
            return False
        return True

    def __repr__(self):
        scope = self.service_id or self.service_type or "—"
        return f"<ClinicalPrivilege doc={self.doctor_id} {scope}>"
