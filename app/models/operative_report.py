"""What happened in the room, written before the child leaves it — SAS.08.

> **SAS.08** Surgical or invasive procedure details are recorded **immediately
> after the procedure**.
>
> The hospital is requested to immediately report the procedure details
> **before the patient leaves the procedural unit**… failure to report these
> events markedly compromises patient care.
>
> The report should address at least the following:
> a) Time of start and time of the end of the procedure.
> b) Name of all staff involved in the procedure, including anesthesia.
> c) **Pre-procedure and post-procedure diagnoses.**
> d) The procedure performed with details and findings.
> e) The details of any implantable device or prosthesis used, **including the
>    batch number**.
> f) **The occurrence of complications or not.**
> g) **Any removed specimen or not.**
> h) Estimated blood loss and/or transfused blood.
> i) Signature of the performing physician.

**Five of the nine are already in the record**, and the program will not ask a
surgeon to type them again: the two stamps (a), the surgeon, anaesthetist and
team (b), the procedure and the operative findings (d), and every implant with
its lot and serial (e) — that last one built for SAS.06 (ز) and SAS.11, which
is why the batch number this standard asks for is already there.

So this table holds the four things nobody records anywhere, plus the
signature.

---

**«or not» is the standard writing this program's own rule down.**

Elements (f) and (g) do not say *record the complications*; they say record
**the occurrence of complications or not**. A blank is not "there were none" —
it is nobody having said, and those are the two facts this codebase has spent
its whole life keeping apart. Both are nullable booleans with a note beside
them, exactly like the equipment that is present-but-not-working and the
imaging that was ordered-but-not-back.

---

**Written and signed are two events.** Element (i) names the signature
separately from the report, and they happen at different moments in a real
theatre: the registrar writes it up while the surgeon is scrubbing out. One
stamp for both would say the surgeon wrote it, which is a claim about a person
rather than a record of one.
"""
from datetime import datetime

from app.extensions import db


class OperativeReport(db.Model):
    """One case's operative report — the written half of SAS.08."""

    __tablename__ = "operative_reports"

    id = db.Column(db.Integer, primary_key=True)
    # **Unique.** One procedure, one report. A second row would be a second
    # account of the same operation with nothing to say which one the ward
    # read — and this is the document post-operative care is planned from.
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, unique=True, index=True)

    # (c) — two diagnoses, and the standard asks for both *because* they can
    # differ: *"any similarity or discrepancy in the patient diagnoses before
    # and after the procedure should be documented and clarified."* One field
    # could not carry a discrepancy at all.
    pre_diagnosis = db.Column(db.Text)
    post_diagnosis = db.Column(db.Text)

    # (f) ``None`` nobody said · ``False`` none occurred · ``True`` they did.
    # The note carries what they were and what was done about them — the
    # intent asks for both: *"Complications … should be recorded, along with
    # the actions taken to manage them."*
    complications = db.Column(db.Boolean)
    complications_note = db.Column(db.Text)

    # (g) the same three states. A specimen that was taken and not named is
    # a specimen the pathology lab cannot match to a child (SAS.10).
    specimen = db.Column(db.Boolean)
    specimen_note = db.Column(db.Text)

    # (h) — **estimated loss and what went back in are two numbers.** The
    # blood already on ``Operation`` is what was *reserved before* the case
    # (SAS.06 و); what was actually lost and actually transfused is a
    # different fact and had nowhere to live.
    blood_loss_ml = db.Column(db.Integer)
    transfused_units = db.Column(db.Integer)

    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    # (i) — its own stamp, and its own person. See the module docstring.
    signed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    signed_at = db.Column(db.DateTime)

    operation = db.relationship("Operation",
                                backref=db.backref("operative_report",
                                                   uselist=False))
    author = db.relationship("User", foreign_keys=[written_by])
    signer = db.relationship("User", foreign_keys=[signed_by])

    #: The fields a person supplies, in the standard's own order.
    WRITTEN = ("pre_diagnosis", "post_diagnosis", "complications", "specimen",
               "blood_loss_ml")

    @property
    def blanks(self):
        """Which written elements are still unanswered.

        **A zero is an answer here and a blank is not.** ``blood_loss_ml`` of
        nought is a real, common and useful thing to record; the check is for
        ``None``, never for falsiness — writing it the lazy way would make
        "no measurable blood loss" indistinguishable from nobody having
        looked.
        """
        out = []
        for name in self.WRITTEN:
            value = getattr(self, name)
            if value is None or (isinstance(value, str) and not value.strip()):
                out.append(name)
        return out

    @property
    def signed(self):
        return self.signed_at is not None

    def __repr__(self):
        return f"<OperativeReport op={self.operation_id}>"
