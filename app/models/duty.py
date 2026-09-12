"""The night somebody covered — and what the clinic owes them for it.

**A second direction for money, beside the one that already existed.** Every
figure in this program until now was a share of something a family paid: a
line on an invoice, a fee on a dose. That answers the doctor who does the
consultation and nothing else. It cannot answer the resident who sits in the
department from ten at night until eight in the morning and bills nobody,
because a shift has no invoice — there is no patient whose bill it is a share
of, and inventing one would put "night cover" on some child's account.

Said plainly, and the sentence this module is built out of: *"الطبيب المقيم
بيتحاسب بالشيفتات"*.

**And it is not only for hospitals.** *"موضوع الشيفتات بتاع الأطباء المقيمين
موجود وليهم حسابات في العيادات الخارجية — في الشيفتات الليلية"*. So the unit is
optional and this module is nobody's corner of ``beds``: a clinic with one
doctor and a resident covering the night must be able to reach it, and gating
it behind the inpatient module would have hidden it from most of the clinics
that need it. This program has built a feature with no door in front of it
often enough to know the shape.

**Rostered is not worked, and the difference is the whole point.** A name in a
square on a wall chart is a plan. Paying for it is paying for a plan. So a
duty starts as *rostered* and pays nothing; somebody says it happened and then
it pays. A past duty nobody has confirmed is left visible and unpaid rather
than quietly settled — the same rule as the round that must not be blank and
the night that is counted once: **an absence must stay visible, because the
program cannot see the corridor.**

**The rate is a row, not a rule in the code.** A slot carries what it pays,
and a doctor may have their own figure for it — exactly the shape
``Service`` and ``DoctorServiceCommission`` already have for consultations,
because it is the same question asked about a different kind of work. And the
amount is **snapshotted onto the duty** when the duty is created, so a rate
edited in March does not rewrite February — the rule ``BedCharge.unit_price``
keeps for the same reason.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

# A duty is planned, then it either happened or it did not. Three states and
# not two: "not worked" and "nobody has said yet" are opposite facts, and
# collapsing them into a flag turns every unconfirmed night into an absence
# on the day the month is closed.
DUTY_STATUSES = ("rostered", "worked", "absent")

# The one that pays. Kept as a name rather than spelled `== "worked"` in six
# files, because the day a fourth state is added is the day the six disagree.
DUTY_PAYABLE = "worked"

# **In the building, or reachable.** Reported as two different things that are
# paid two different ways: *«تحت الطلب او اون كول بيتحاسب طريقة مختلفة»*.
#
# And they are not degrees of the same thing — they are the answer to two
# different questions on the night something goes wrong. "Who is here" is
# somebody you fetch; "who is on call" is somebody you ring and then wait for.
# A rota that showed only names would leave whoever is holding the phone at
# three in the morning to guess which they had.
DUTY_COVER = ("present", "on_call")

#: The rotas a theatre runs, seeded into :class:`DutyRole`.
#:
#: Asked for as three lists and not one: *«خلى كل لسيت لواحده — لسيت الطبيب
#: الجراح لواحده وليست دكتور التخدير لواحده وليست التمريض لواحده»*. One list
#: with three kinds of person on it is a list nobody can read at speed, and
#: speed is the only reason it exists.
DUTY_ROLES = ["surgeon", "anaesthesia", "nursing"]

#: Icon per built-in rota, so a screen read in a hurry is read by shape.
DUTY_ROLE_ICONS = {
    "surgeon": "bi-scissors",
    "anaesthesia": "bi-lungs",
    "nursing": "bi-bandaid",
}


class DutySlot(db.Model):
    """A named stretch of cover — صباحي، مسائي، ليلي — and what it pays.

    The three shifts a hospital runs are a **catalogue**, not a constant: the
    hours differ between departments and countries, Ramadan moves them, and a
    clinic that runs two shifts instead of three must not be told it has an
    empty evening. So the names, the hours and the rate are all typed on a
    screen.
    """

    __tablename__ = "duty_slots"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    # What one of these pays by default. Nullable is not "free" — it is "not
    # decided yet", and a duty created against a slot with no rate is worth
    # nothing until somebody sets one. See ``utils/duty.rate_for``.
    rate = db.Column(db.Float)
    # What the same stretch pays **on call** — at home with a phone, rather
    # than in the building. NULL is "nobody set one", not "the same as
    # being here": a clinic that has not decided what on-call is worth should
    # see an empty figure and be asked, not have the presence rate quietly
    # paid for a night somebody spent at home.
    on_call_rate = db.Column(db.Float)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    overrides = db.relationship("DutyRate", back_populates="slot",
                                cascade="all, delete-orphan")

    @property
    def crosses_midnight(self):
        """Whether this slot ends on the next day.

        The night shift is ten at night to eight in the morning, and every
        naive ``start < end`` comparison in a rota screen gets it wrong. Read
        off the times rather than stored as a flag somebody can set to
        disagree with the hours beside it.
        """
        return self.end_time is not None and self.start_time is not None \
            and self.end_time <= self.start_time

    def rate_for(self, doctor=None, cover="present"):
        """What this slot pays this doctor, for this kind of cover.

        The same fallback ``Service.commission_for`` uses, and deliberately so
        — a clinic that has agreed a different night rate with one registrar
        should not need a second slot to express it. ``cover`` picks which
        pair of figures is being asked about: being in the building, or being
        reachable from home.

        **On call never falls back to the presence rate.** A clinic that has
        not said what a night at home is worth gets zero and a screen that
        says so — paying the full presence figure for it would be the program
        deciding a rate nobody agreed.
        """
        doctor_id = getattr(doctor, "id", doctor)
        on_call = cover == "on_call"
        if doctor_id:
            for row in self.overrides:
                if row.doctor_id != doctor_id:
                    continue
                own = row.on_call_amount if on_call else row.amount
                if own is not None:
                    return float(own)
        return float((self.on_call_rate if on_call else self.rate) or 0)

    def __repr__(self):
        return f"<DutySlot {self.name}>"


class DutyRate(db.Model):
    """One doctor's own rate for one slot."""

    __tablename__ = "duty_rates"
    __table_args__ = (
        db.UniqueConstraint("doctor_id", "slot_id", name="uq_duty_rate"),
    )

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("duty_slots.id"),
                        nullable=False, index=True)
    amount = db.Column(db.Float)
    # Their own figure for a night at home. NULL falls back to the slot's,
    # exactly as ``amount`` does — and a slot with no on-call figure pays
    # nothing, which is a question for somebody rather than a rate to invent.
    on_call_amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User", foreign_keys=[doctor_id])
    slot = db.relationship("DutySlot", back_populates="overrides")


class Duty(db.Model):
    """One person covering one slot on one day.

    **Once.** The database refuses a second row for the same person, slot and
    day — the rule the bed nights keep, for the same reason: a duty entered
    twice is paid twice, and no screen catches it because both rows look
    right.
    """

    __tablename__ = "duties"
    __table_args__ = (
        db.UniqueConstraint("doctor_id", "slot_id", "on_date",
                            name="uq_duty_once"),
    )

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("duty_slots.id"),
                        nullable=False, index=True)
    # **Optional, and that is the feature.** A night in the clinic is covered
    # by somebody who is not in any department, because the clinic has no
    # departments. Requiring a unit here would have made this a hospital-only
    # screen and left out the clinics that asked for it.
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=True, index=True)
    # The clinic's own date — the day the rota says, not a UTC instant. A
    # night shift starting at ten on Tuesday is Tuesday's duty even though
    # most of it happens on Wednesday, which is how everybody who works one
    # talks about it.
    on_date = db.Column(db.Date, default=local_today, nullable=False,
                        index=True)
    # **Which rota this is.** Three lists and not one — the surgeons, the
    # anaesthetists, the nursing — because a single list with three kinds of
    # person on it is a list nobody can read at speed, and speed is the only
    # reason it exists.
    #
    # NULL is **general cover**, which is what every duty rostered before this
    # column was: the resident covering the department, belonging to no
    # theatre rota. Not "a surgeon whose row is incomplete".
    role = db.Column(db.String(30), index=True)
    # In the building, or reachable from home. Defaulted rather than left
    # empty on the rows that already exist, because for them it is not
    # unknown: on-call did not exist when they were rostered, so every one of
    # them was somebody actually here.
    cover = db.Column(db.String(10), default="present", nullable=False,
                      index=True)
    status = db.Column(db.String(10), default="rostered", nullable=False,
                       index=True)
    # Snapshotted from the slot when the duty is created — see the module
    # docstring. Nullable means "there was no rate to take", which is a thing
    # a screen should say out loud rather than a zero it should invent.
    amount = db.Column(db.Float)
    note = db.Column(db.String(160))

    confirmed_at = db.Column(db.DateTime)
    confirmed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    doctor = db.relationship("User", foreign_keys=[doctor_id])
    slot = db.relationship("DutySlot")
    unit = db.relationship("Unit")

    @property
    def is_payable(self):
        return self.status == DUTY_PAYABLE

    @property
    def pay(self):
        """What this duty is worth — nothing at all unless it was worked."""
        return round(self.amount or 0, 2) if self.is_payable else 0.0

    def __repr__(self):
        return f"<Duty {self.doctor_id} {self.on_date} {self.status}>"


class DutyRole(db.Model):
    """The rotas this clinic runs — the surgeons, the anaesthetists, nursing.

    A catalogue and not a constant, for the reason the case kinds and the
    bill sections are: **nothing reads a role by name.** A rota is drawn by
    grouping duties under whatever roles exist, so a hospital that also runs
    a «أشعة» list on call gets one the minute somebody types it.
    """

    __tablename__ = "duty_roles"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    icon = db.Column(db.String(40))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Seeded rows keep their key: a clinic renaming «التمريض» must not thereby
    # detach every night already rostered under it.
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    def display_name(self, lang="ar"):
        name = self.name_en if lang == "en" else self.name_ar
        if name:
            return name
        from app.i18n import t

        key = "duty_roles." + self.key
        try:
            label = t(key)
        except RuntimeError:
            return self.key
        return label if label != key else self.key

    def __repr__(self):
        return f"<DutyRole {self.key}>"
