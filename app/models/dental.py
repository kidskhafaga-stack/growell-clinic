"""The tooth chart, for a clinic whose patients are children.

**Numbered the way a child's mouth actually is.** FDI two-digit notation, which
is what Egyptian dental schools teach and what every referral in the country
is written in: the first digit is the quadrant, the second is the tooth
counting out from the midline. Permanent teeth take quadrants 1–4, primary
teeth 5–8 — so 16 is the adult first molar and 55 is the baby one above it,
and the number itself says which dentition it belongs to.

That is the whole reason for choosing FDI over the Universal 1–32/A–T that a
general dental program might use. A paediatric clinic lives in **mixed
dentition**: between roughly six and twelve a child has both sets at once, one
falling out while the other comes in, and a chart that cannot hold both is
useless for exactly the ages this clinic sees most. In FDI a mixed mouth is
just a set of numbers; in Universal it needs two charts and a rule about which
one is showing.

**A finding belongs to a surface, not to a tooth.** Caries on the biting
surface of 55 and a filling on the surface between 55 and 54 are two different
facts about one tooth, and a chart that stores "55: caries" cannot say which
face to drill or notice that the second one is new. Anterior teeth have no
occlusal surface and molars have no incisal edge, so the surfaces a tooth
offers depend on the tooth — asking for a surface it does not have is refused
rather than stored.

**Nothing is deleted.** A tooth that was filled last year and is decayed again
this year has a history, and that history is the argument for a crown. Each
finding is a row with a date; the chart shows the latest per surface and the
file keeps the rest.
"""
from datetime import datetime

from app.extensions import db

# --- how a mouth is numbered ----------------------------------------------
# Quadrants clockwise from the patient's upper right, as every dental chart in
# the world is drawn — which is the patient's right on the *left* of the page.
PERMANENT_QUADRANTS = (1, 2, 3, 4)
PRIMARY_QUADRANTS = (5, 6, 7, 8)

# Eight permanent teeth per quadrant, five primary.
PERMANENT_TEETH = [q * 10 + n for q in PERMANENT_QUADRANTS for n in range(1, 9)]
PRIMARY_TEETH = [q * 10 + n for q in PRIMARY_QUADRANTS for n in range(1, 6)]
ALL_TEETH = PERMANENT_TEETH + PRIMARY_TEETH


def is_primary(tooth):
    """Whether this FDI number is a baby tooth. The number says so itself."""
    return tooth // 10 in PRIMARY_QUADRANTS


def tooth_position(tooth):
    """Position within the quadrant, 1 at the midline."""
    return tooth % 10


# What a tooth *is*, which is what decides how it is drawn.
#
# The number alone cannot answer this, and that is the whole point of the
# function. Position 4 in a permanent quadrant is a premolar; position 4 in a
# primary quadrant is a **molar**, because the primary set has no premolars at
# all — twenty teeth, not twenty-eight, and the two premolars that eventually
# stand there erupt underneath the primary molars and replace them.
#
# A chart that reads the last digit and stops draws a child's mouth with four
# teeth that do not exist in it. That is an adult chart shrunk down, and it is
# the difference between a paediatric dental chart and a dental chart.
TOOTH_KINDS = ("incisor", "canine", "premolar", "molar")


def tooth_kind(tooth):
    """What kind of tooth an FDI number is.

    One of ``incisor``, ``canine``, ``premolar``, ``molar``.
    """
    position = tooth_position(tooth)
    if position <= 2:
        return "incisor"
    if position == 3:
        return "canine"
    if is_primary(tooth):
        return "molar"          # no premolars in the primary dentition
    return "premolar" if position <= 5 else "molar"


def is_anterior(tooth):
    """Incisors and canines — the teeth with an incisal edge and no biting
    table. Positions 1–3 in every quadrant, primary and permanent alike."""
    return tooth_position(tooth) <= 3


# --- the faces of a tooth --------------------------------------------------
# Five surfaces, and a sixth entry for a finding that is about the whole tooth
# rather than one of its faces: a tooth that is missing, unerupted, or to be
# extracted is not missing "on the buccal side".
SURFACES = ["mesial", "distal", "buccal", "lingual", "occlusal", "incisal"]
WHOLE_TOOTH = "whole"

# And a seventh, for the one finding that is not about the tooth at all.
#
# A space maintainer is fitted where a tooth **is not**. Filed under "whole"
# it would be the latest whole-tooth finding on that position and would
# replace the extraction in the chart — so a tooth that is gone, and is being
# held open precisely because it is gone, would read as neither extracted nor
# missing. Two facts, one slot, and the more important one loses.
#
# Mutation testing found this: the check that a fitted maintainer settles the
# question could be deleted with nothing failing, because the maintainer had
# already overwritten the extraction that raised it.
SPACE = "space"

# A molar has a biting table; an incisor has an edge. Offering both on every
# tooth is how a chart ends up holding an occlusal finding on a lower incisor,
# which is not a place that exists.
ANTERIOR_SURFACES = ["mesial", "distal", "buccal", "lingual", "incisal"]
POSTERIOR_SURFACES = ["mesial", "distal", "buccal", "lingual", "occlusal"]


def surfaces_of(tooth):
    """The faces this tooth actually has, plus the whole-tooth entry.

    ``SPACE`` is not offered here. It is not a face a dentist picks — it is
    where the program files a space maintainer, and it files it there itself.
    """
    faces = ANTERIOR_SURFACES if is_anterior(tooth) else POSTERIOR_SURFACES
    return faces + [WHOLE_TOOTH]


# Conditions that live in their own slot rather than on a face or on the
# whole tooth. Kept as a map so the rule is stated once and read by both the
# chart form and anything else that writes a finding.
SLOT_CONDITIONS = {"space_maintainer": SPACE}


def slot_for(condition, surface):
    """Where a finding of this condition belongs."""
    if condition in SLOT_CONDITIONS:
        return SLOT_CONDITIONS[condition]
    if condition in WHOLE_TOOTH_CONDITIONS:
        return WHOLE_TOOTH
    return surface


# --- what can be true of a surface ----------------------------------------
# Deliberately short, and paediatric. A general dental list carries implants
# and bridges; a five-year-old has neither, and a screen offering them is a
# screen somebody has to read past every time.
#
# `sound` is on the list because recording that a tooth was **examined and
# found healthy** is different from never having looked at it, and the
# difference is most of what a recall appointment is for.
CONDITIONS = [
    "sound",            # سليم — looked at, nothing found
    "caries",           # تسوس
    "filled",           # حشو
    "sealant",          # حشو وقائي (fissure sealant)
    "pulpotomy",        # بتر عصب — the paediatric pulp treatment
    "root_canal",       # علاج جذور
    "crown",            # تلبيس (stainless steel crown, usually)
    "extracted",        # مخلوع
    "missing",          # مفقود — never present, or lost before we saw them
    "unerupted",        # لم يبزغ
    "erupting",         # في مرحلة البزوغ
    "mobile",           # مخلخل — the baby tooth about to come out
    "trauma",           # كسر / إصابة
    "discoloured",      # تغير لون
    "space_maintainer",  # حافظ مسافة — see below
]

# Conditions that describe the whole tooth and cannot sit on one face.
WHOLE_TOOTH_CONDITIONS = {"extracted", "missing", "unerupted", "erupting",
                          "mobile", "crown", "root_canal", "pulpotomy",
                          "space_maintainer"}

# Findings that mean somebody has to do something about this tooth.
#
# **This is not a treatment plan and must never become one.** It says the
# tooth is outstanding, not what to do to it: caries can be a filling, a
# pulpotomy or an extraction depending on how deep it has gone and how long
# the tooth has left, and that is the dentist's call in front of the child.
# A program that read "caries" and wrote "filling" onto a plan would be
# prescribing from a keyword, and would be wrong on the cases that matter
# most.
#
# What it earns is one thing: the chart can offer a tooth to the plan with
# the finding attached, so the fact is carried across instead of typed twice.
NEEDS_WORK = {"caries", "trauma", "mobile", "discoloured"}


# --- the space a baby tooth leaves behind --------------------------------
#
# A primary molar taken out early does not just leave a gap. The teeth beside
# it drift into it, and by the time the premolar underneath is ready to come
# through there is nowhere for it to go — so it comes in crooked, or does not
# come in at all. A space maintainer holds the gap open until it does. This is
# one of the defining jobs of paediatric dentistry and the reason the chart
# has to know about it at all.
#
# **Which teeth.** The primary molars — positions 4 and 5 in each primary
# quadrant. Not the incisors: a child who loses an upper front baby tooth
# early loses very little space, and fitting an appliance for it is a
# cosmetic decision rather than a space one. Putting them on this list would
# raise the question on every toddler who fell over, which is how a warning
# becomes something people click past.
SPACE_KEEPING_POSITIONS = (4, 5)

# Teeth whose position is no longer being held by anything.
GONE = {"extracted", "missing"}

# The successor is up and taking the space itself, so nothing needs holding.
COMING_THROUGH = {"erupting"}


def successor_of(tooth):
    """The permanent tooth that replaces this primary one, or ``None``.

    The numbering does the work: primary quadrants 5–8 sit directly over
    permanent quadrants 1–4 at the same position, so 55 is replaced by 15 and
    75 by 35. Only meaningful for primary teeth — a permanent tooth has no
    successor, which is the whole reason losing one matters more.
    """
    if not is_primary(tooth):
        return None
    return (tooth // 10 - 4) * 10 + tooth_position(tooth)


def spaces_to_decide(chart):
    """Primary molar spaces with nothing holding them and no decision on file.

    Returns ``{tooth: successor}``.

    **This raises a question; it does not answer one.** Whether a space
    maintainer goes in depends on how close the premolar underneath is to
    erupting, on the child's age, and on whether the successor is there at
    all — read off an X-ray, in front of the child. A program that saw
    "extracted" and wrote "fit a space maintainer" would be prescribing from a
    keyword, exactly as one that read "caries" and wrote "filling" would be.

    What it earns is that nobody has to notice. A molar taken out in March is
    a space that closes quietly over the summer, and the visit where somebody
    would have spotted it is the one where the child came in about something
    else.
    """
    out = {}
    for tooth, surfaces in chart.items():
        if not is_primary(tooth):
            continue
        if tooth_position(tooth) not in SPACE_KEEPING_POSITIONS:
            continue
        conditions = {row.condition for row in surfaces.values()}
        if not conditions & GONE:
            continue
        # Already answered — something is holding it.
        if "space_maintainer" in conditions:
            continue
        successor = successor_of(tooth)
        # And answered the other way: the permanent tooth is on its way, so
        # the space is being taken rather than lost.
        below = chart.get(successor) or {}
        if {row.condition for row in below.values()} & COMING_THROUGH:
            continue
        out[tooth] = successor
    return out


def outstanding(chart):
    """Teeth with something on them that has not been dealt with.

    ``chart`` is what :func:`chart_for` returns. The latest finding per
    surface decides: a surface that was decayed and is now filled is settled,
    because the newer row replaced the older one in the chart.
    """
    out = {}
    for tooth, surfaces in chart.items():
        hits = [(surface, row) for surface, row in surfaces.items()
                if row.condition in NEEDS_WORK]
        if hits:
            out[tooth] = hits
    return out


class ToothFinding(db.Model):
    """One thing observed about one surface of one tooth, on one day."""

    __tablename__ = "tooth_findings"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The visit it was found in, when it was found in one. Nullable: a chart
    # can be filled in from a referral letter or a previous clinic's notes,
    # and refusing that would mean the first visit starts from an empty mouth
    # nobody believes.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    tooth = db.Column(db.Integer, nullable=False, index=True)   # FDI
    surface = db.Column(db.String(10), default=WHOLE_TOOTH, nullable=False)
    condition = db.Column(db.String(20), nullable=False, index=True)
    note = db.Column(db.String(300))

    found_on = db.Column(db.Date, nullable=False, index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    visit = db.relationship("Visit")
    recorder = db.relationship("User")

    @classmethod
    def record(cls, patient_id, tooth, condition, surface=None, **rest):
        """Write a finding, placed where that condition belongs.

        The placement rule lives here rather than in the route that happens to
        call it. It had been in the route, and the test helper wrote rows
        straight to the model — two ways of doing the same thing, and the one
        the tests used did not know that a space maintainer goes in its own
        slot. Mutation testing showed it up: the check that a fitted
        maintainer settles the space could be deleted with nothing failing,
        because in the tests the maintainer was still landing on top of the
        extraction.
        """
        return cls(patient_id=patient_id, tooth=tooth, condition=condition,
                   surface=slot_for(condition, surface or WHOLE_TOOTH), **rest)

    @property
    def primary(self):
        return is_primary(self.tooth)

    def __repr__(self):
        return f"<ToothFinding {self.tooth}/{self.surface} {self.condition}>"


def chart_for(patient_id, upto=None):
    """The mouth as it stands: the latest finding per tooth and surface.

    Returns ``{tooth: {surface: ToothFinding}}``. History is not thrown away —
    it is simply not what a chart is. A tooth filled last year and decayed
    again this year shows the decay, and the file still holds both, which is
    the argument for a crown.

    One query. The chart is drawn on the patient's file beside everything
    else, and a screen that asks per tooth is fifty-two queries to draw a
    picture of one mouth.
    """
    query = ToothFinding.query.filter(ToothFinding.patient_id == patient_id)
    if upto is not None:
        query = query.filter(ToothFinding.found_on <= upto)
    rows = query.order_by(ToothFinding.found_on, ToothFinding.id).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.tooth, {})[row.surface] = row
    return latest


def history_for(patient_id, tooth):
    """Everything ever recorded about one tooth, oldest first."""
    return (ToothFinding.query
            .filter(ToothFinding.patient_id == patient_id,
                    ToothFinding.tooth == tooth)
            .order_by(ToothFinding.found_on, ToothFinding.id).all())
