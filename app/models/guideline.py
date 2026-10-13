"""Clinical practice guidelines — GAHAR ICD.16, and ICD.04 for emergencies.

*"At least three clinical guidelines, for the most common/high risk three
diagnoses managed in the hospital, are adopted/adapted in the hospital
annually"* (ICD.16 ev. 3), each *"reviewed and updated at least every 2
years"* (e). Both numbers are the standard's own and are used as written.

A guideline row is the hospital's adoption of one: where it came from and
whether it is national (d), why it was chosen and by which panel (a i–ii),
who approved it locally (a iv), the implementation plan (a v), and where the
document itself is. Training sessions (ev. 4), adherence checks (c) and
reviews (e) are events on it. ICD.04 names the emergencies a hospital
adopts guidelines for, "when applicable" — the board shows which of them have
none, and does not call that a failure.
"""
from datetime import datetime

from app.extensions import db

SCOPES = ("emergency", "diagnosis", "other")
#: ICD.04 (a)–(f), and (g) the hospital's other emergencies.
EMERGENCY_TOPICS = ("chest_pain", "shock", "polytrauma", "consciousness", "asthma", "stroke", "other")
EVENT_KINDS = ("training", "audit", "review")
#: ICD.16 (e) — the standard's own interval, in years.
REVIEW_YEARS = 2
#: ICD.16 ev. 3 — the standard's own number per year.
PER_YEAR = 3


class ClinicalGuideline(db.Model):
    __tablename__ = "clinical_guidelines"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    scope = db.Column(db.String(10), nullable=False, default="diagnosis")
    topic = db.Column(db.String(16))
    source = db.Column(db.String(160))
    is_national = db.Column(db.Boolean, default=False, nullable=False)
    selection = db.Column(db.Text)
    panel = db.Column(db.String(255))
    approved_by = db.Column(db.String(160), nullable=False)
    adopted_on = db.Column(db.Date, nullable=False, index=True)
    plan = db.Column(db.Text)
    link = db.Column(db.String(255))
    reviewed_on = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    events = db.relationship("GuidelineEvent", back_populates="guideline",
                             order_by="GuidelineEvent.held_on.desc()", cascade="all, delete-orphan")

    @property
    def review_due(self):
        base = self.reviewed_on or self.adopted_on
        try:
            return base.replace(year=base.year + REVIEW_YEARS)
        except ValueError:  # 29 February
            return base.replace(year=base.year + REVIEW_YEARS, day=28)

    @property
    def safe_link(self):
        link = (self.link or "").strip()
        return link if link.lower().startswith(("http://", "https://")) else None


class GuidelineEvent(db.Model):
    __tablename__ = "guideline_events"

    id = db.Column(db.Integer, primary_key=True)
    guideline_id = db.Column(db.Integer, db.ForeignKey("clinical_guidelines.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    held_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    guideline = db.relationship("ClinicalGuideline", back_populates="events")
