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

# A molar has a biting table; an incisor has an edge. Offering both on every
# tooth is how a chart ends up holding an occlusal finding on a lower incisor,
# which is not a place that exists.
ANTERIOR_SURFACES = ["mesial", "distal", "buccal", "lingual", "incisal"]
POSTERIOR_SURFACES = ["mesial", "distal", "buccal", "lingual", "occlusal"]


def surfaces_of(tooth):
    """The faces this tooth actually has, plus the whole-tooth entry."""
    faces = ANTERIOR_SURFACES if is_anterior(tooth) else POSTERIOR_SURFACES
    return faces + [WHOLE_TOOTH]


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
]

# Conditions that describe the whole tooth and cannot sit on one face.
WHOLE_TOOTH_CONDITIONS = {"extracted", "missing", "unerupted", "erupting",
                          "mobile", "crown", "root_canal", "pulpotomy"}


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
