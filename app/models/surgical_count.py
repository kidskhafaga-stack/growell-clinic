"""Counting what goes into a child, and what comes back out — GAHAR SAS.09.

> **SAS.09 · GSR.17** The accuracy of counting sponges, needles, and
> instruments pre- and post-procedure is verified.
>
> Missing sponges, suture reels, needles, blades, towels, or instruments
> inside the patient's body act as a foreign body and cause serious morbidity…
> which necessitate reopening the patient and could reach up to mortality.
>
> Evidence of compliance:
> 2. **Two staff members** count sponges, needles, towels, or instruments
>    before, during, and after the surgery, **as the second one acts as a
>    witness for the first one**.
> 3. The preoperative, intraoperative, and postoperative counts are recorded,
>    **and the performing physician signs the record**.
> 4. There is a process to manage and deal with **miscounts** once identified.

**What the program had was a tick.** ``counts_correct`` is one of the items on
the sign-out stop of the WHO checklist, and anybody could tick it on the way
past. One box, no numbers, no second person, no three moments, and nothing at
all to say what happened when the numbers disagreed — which is the one moment
this standard exists for.

That is the same false green tick this codebase has already taken out of the
consent, the site, the identity and the discharge summary, and it is taken out
the same way: **the item is derived from a record of something that happened**,
never ticked.

---

**Why two tables.**

``SurgicalCount`` is *one counting event*: a moment, the two people who did
it, and when. ``SurgicalCountItem`` is *one kind of thing* counted in that
event, with the number expected and the number found.

Keeping the items in their own rows is what lets a miscount name itself. A
single "counts correct?" boolean on the event could say that something was
wrong; only a row per item can say **four sponges expected and three found**,
which is the sentence that sends somebody to the X-ray department.

---

**Expected and found, never one number.**

The temptation is a single "count" column. It cannot work: the whole standard
is about the *difference* between what went in and what came back, and a
program holding one number has thrown away the comparison before anybody
looked at it.
"""
from datetime import datetime

from app.extensions import db

#: The three moments the standard names, in order. The intent describes them
#: as *"before, during the closure of each body space, and after the closure
#: of the skin"*, and evidence 3 names them **preoperative, intraoperative and
#: postoperative** — which is what these keys are.
COUNT_MOMENTS = ("pre", "intra", "post")

#: What gets counted. Quoted from the standard — the statement names sponges,
#: needles and instruments, and the intent adds *"suture reels, blades,
#: towels"*. Nothing has been added to this list, and a clinic that counts
#: something else writes it in the note rather than the program inventing a
#: vocabulary for it.
COUNT_ITEMS = ("sponge", "needle", "instrument", "towel", "blade", "suture")


class SurgicalCount(db.Model):
    """One counting event: a moment, two people, and what they found."""

    __tablename__ = "surgical_counts"

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)

    #: ``pre`` · ``intra`` · ``post`` — see :data:`COUNT_MOMENTS`.
    moment = db.Column(db.String(8), nullable=False, index=True)

    # **Two people, and the second is not decoration.** Evidence 2 says the
    # second *"acts as a witness for the first one"*, which is the whole
    # control: one person counting alone is the failure mode this standard
    # was written against. `surgical_counts.record` refuses a witness who is
    # the same person as the counter — a signature by one person twice is one
    # person, whatever the form says.
    counted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    witnessed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note = db.Column(db.String(255))

    # ---------------------------------------- when the numbers disagree ----
    #
    # Evidence 4 asks for *a process to manage and deal with miscounts*, and
    # the intent says what it is: *"the team shall conduct re-counting, check
    # the missing item, make provisions using imaging studies, and report the
    # miscount."*
    #
    # **Three states each, not two.** ``None`` is *nobody has said*, ``False``
    # is *it was decided against*, ``True`` is *it was done*. A plain boolean
    # would make "we did not X-ray this child" and "nobody has got to that
    # yet" the same row, and those are opposite facts at the moment a sponge
    # is unaccounted for.
    recounted = db.Column(db.Boolean)
    imaging = db.Column(db.Boolean)

    #: How it ended, in the team's own words. Free text because the standard
    #: does not name the outcomes and this program does not invent clinical
    #: vocabularies — see the cancellation reasons.
    resolution = db.Column(db.Text)

    # Reported (intent: *"and report the miscount"*), which is its own event:
    # a miscount resolved on the table and a miscount reported to whoever
    # collects incidents are two different things, and evidence 5 monitors the
    # second.
    reported_at = db.Column(db.DateTime)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    operation = db.relationship("Operation",
                                backref=db.backref("counts",
                                                   cascade="all, delete-orphan"))
    counter = db.relationship("User", foreign_keys=[counted_by])
    witness = db.relationship("User", foreign_keys=[witnessed_by])
    reporter = db.relationship("User", foreign_keys=[reported_by])

    @property
    def short(self):
        """The items whose numbers did not agree — the finding itself."""
        return [i for i in self.items if not i.agrees]

    @property
    def agrees(self):
        """Whether every item counted at this moment came back."""
        return not self.short

    @property
    def reported(self):
        return self.reported_at is not None

    def __repr__(self):
        return f"<SurgicalCount {self.moment} op={self.operation_id}>"


class SurgicalCountItem(db.Model):
    """One kind of thing, counted at one moment: how many went in, how many
    came back."""

    __tablename__ = "surgical_count_items"

    id = db.Column(db.Integer, primary_key=True)
    count_id = db.Column(db.Integer, db.ForeignKey("surgical_counts.id"),
                         nullable=False, index=True)

    #: A key from :data:`COUNT_ITEMS`.
    item = db.Column(db.String(16), nullable=False)
    expected = db.Column(db.Integer, nullable=False, default=0)
    found = db.Column(db.Integer, nullable=False, default=0)

    count = db.relationship("SurgicalCount",
                            backref=db.backref("items",
                                               cascade="all, delete-orphan"))

    @property
    def agrees(self):
        return self.expected == self.found

    @property
    def missing(self):
        """How many are unaccounted for — **positive means inside somebody**.

        Signed on purpose. A negative is an extra item on the trolley that
        nobody expected, which is its own kind of wrong and must not read as
        a clean count.
        """
        return self.expected - self.found

    def __repr__(self):
        return f"<SurgicalCountItem {self.item} {self.found}/{self.expected}>"
