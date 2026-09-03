"""Where a child physically is: the unit, the space and the bed.

**Not ``ClinicRoom``.** That one is the consulting عيادة — the room a doctor
sits in to see outpatients, assigned per day. This is the other kind of place
entirely: somewhere a child *stays*, for hours or for weeks, with a bed in it.
Two words that both translate as "room" and mean nothing like each other, so
they are two tables and the difference is stated here rather than discovered.

**Three levels, one shape, four departments.**

    Unit (القسم)  →  Space (الحيّز)  →  Bed (السرير)

Described from the floor by the person who runs the place: *"الطوارئ بيبقوا
شغالين بارتشن بيتسكن فيه السرير، والداخلي غرفة بيتسكن فيها سرير، وفي العناية
فيه عزل لوحده وبيبقى فيه ٢ او ١ بارتشن عزل والباقي سرير تقريباً، والحضانة فيه
سرير وفيه حضانة وفيه كبسولة."*

That sentence is the whole reason the middle level is called a **space** and
not a room. Emergency runs on partitions; the ward runs on rooms; intensive
care is an open bay with one or two isolation partitions in it; the incubator
unit is a bay holding three different kinds of bed. "Room" would have been
wrong in three of those four, and a table per department would have been the
same table written four times.

**Isolation is a flag on the space, not a kind of its own and never a
property of the bed.** Not a kind, because "an isolation partition" and "an
isolation room" are both real and a kind list would have to carry every
combination. Not on the bed, because a bay with six beds and one of them
marked "isolated" is information that lies — there is no wall around it. What
isolates is the space.

**Nothing here stores whether a bed is free.** Occupancy is worked out from
open stays (see ``admission.py``). A flag on the bed is one forgotten
discharge away from a ward that says it is full while three beds stand empty,
and this project has already paid for that lesson once.
"""
from datetime import datetime

from app.extensions import db

# The four departments the plan names, plus the two smaller ones that share
# the same shape. A *kind*, not a table: they differ by how often a child is
# looked at, not by what a bed is (see HOSPITAL_PLAN.md, ٤-ب).
UNIT_KINDS = ("emergency", "nicu", "icu", "ward", "day_care", "recovery")

# What the middle level physically is. Isolation is not here — see below.
SPACE_KINDS = ("partition", "room", "bay")

# What is actually in the space. The incubator unit holds three of these at
# once, which is why the kind belongs to the bed and not to the unit.
BED_KINDS = ("bed", "cot", "incubator", "capsule", "trolley")


class Unit(db.Model):
    """A department: emergency, the incubators, intensive care, a ward."""

    __tablename__ = "care_units"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(16), nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    spaces = db.relationship("Space", back_populates="unit",
                             order_by="Space.sort_order, Space.id")

    def __repr__(self):
        return f"<Unit {self.name} ({self.kind})>"


class Space(db.Model):
    """A partition, a room or an open bay — whatever holds the beds."""

    __tablename__ = "care_spaces"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="room")

    # Asked at the moment an infectious child is coming in, which is never a
    # quiet moment: "is there an isolation space free?" A screen cannot answer
    # that from a room name, and a clinic that writes "عزل" into the name is
    # keeping the fact in a place nothing can query.
    is_isolation = db.Column(db.Boolean, default=False, nullable=False,
                             index=True)

    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unit = db.relationship("Unit", back_populates="spaces")
    beds = db.relationship("Bed", back_populates="space",
                           order_by="Bed.sort_order, Bed.id")

    def __repr__(self):
        return f"<Space {self.name} ({self.kind})>"


class Bed(db.Model):
    """One bed, cot, incubator, transport capsule or emergency trolley."""

    __tablename__ = "care_beds"

    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey("care_spaces.id"),
                         nullable=False, index=True)
    name = db.Column(db.String(40), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="bed")
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # Out of service — being cleaned, broken, or waiting for an engineer. Not
    # deleted: a bed that is deleted takes its stays with it, and last month's
    # occupancy is a number a hospital reports on.
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    out_of_service_note = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    space = db.relationship("Space", back_populates="beds")

    @property
    def unit(self):
        return self.space.unit if self.space else None

    @property
    def is_isolation(self):
        """Isolation comes from the space this bed stands in — never stored
        here. See the module docstring: a bed in an open bay cannot isolate
        anybody however it is labelled."""
        return bool(self.space and self.space.is_isolation)

    def __repr__(self):
        return f"<Bed {self.name} ({self.kind})>"
