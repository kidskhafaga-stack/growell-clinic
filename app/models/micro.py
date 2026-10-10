"""Microbiology — what grew, and what it is sensitive to.

A culture used to be answered in the report box, in words: «E. coli >10⁵,
sensitive to …». Words a doctor can read, and nothing else can: the
infection-control nurse cannot count the MRSA this year, the pharmacy cannot
see which antibiotic the ward's E. coli still answers to, and the next
doctor cannot see last month's isolate beside this one.

So a culture is answered in its own shape: **growth or none**, the
**isolates** — each an organism from the laboratory's own list, with its
count — and for each isolate **its susceptibility** to the antibiotics the
laboratory tested, read S, I or R **by the laboratory**. The program does
not read a zone or an MIC; the breakpoints are the laboratory's standard and
its own reading.

Both lists are the laboratory's — the organisms it reports and the
antibiotics on its panels. Nothing is preset; a laboratory adds them once,
in one paste. An organism the laboratory marks **alert** (MRSA, ESBL…) is
said wherever it is reported.

The words are still written: the summary of the structured answer goes into
the order's report text, so every screen that already reads it — the
doctor's inbox, the file, the print — goes on reading it.
"""
from datetime import datetime

from app.extensions import db

OUTCOMES = ("no_growth", "growth", "mixed", "contaminated")
READINGS = ("S", "I", "R")


class MicroOrganism(db.Model):
    __tablename__ = "micro_organisms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    #: Said wherever it is reported — the laboratory's and infection
    #: control's list of what needs acting on (MRSA, ESBL, CRE…).
    alert = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MicroAntibiotic(db.Model):
    __tablename__ = "micro_antibiotics"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class CultureResult(db.Model):
    """One culture's answer — on the order it answers."""
    __tablename__ = "culture_results"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"),
                         nullable=False, unique=True, index=True)
    outcome = db.Column(db.String(14))
    #: A preliminary report is a real report («no growth at 24 hours») and
    #: says it is one until the final.
    final = db.Column(db.Boolean, default=False, nullable=False)
    comment = db.Column(db.Text)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order = db.relationship("VisitInvestigation", backref=db.backref("culture", uselist=False))
    isolates = db.relationship("CultureIsolate", back_populates="culture",
                               cascade="all, delete-orphan",
                               order_by="CultureIsolate.sort_order")


class CultureIsolate(db.Model):
    __tablename__ = "culture_isolates"

    id = db.Column(db.Integer, primary_key=True)
    culture_id = db.Column(db.Integer, db.ForeignKey("culture_results.id"),
                           nullable=False, index=True)
    organism_id = db.Column(db.Integer, db.ForeignKey("micro_organisms.id"),
                            nullable=False, index=True)
    #: As the laboratory writes it — «>10^5 CFU/mL», «heavy growth».
    count = db.Column(db.String(60))
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    culture = db.relationship("CultureResult", back_populates="isolates")
    organism = db.relationship("MicroOrganism")
    readings = db.relationship("CultureSusceptibility", back_populates="isolate",
                               cascade="all, delete-orphan")


class CultureSusceptibility(db.Model):
    __tablename__ = "culture_susceptibilities"
    __table_args__ = (db.UniqueConstraint("isolate_id", "antibiotic_id",
                                          name="uq_isolate_antibiotic"),)

    id = db.Column(db.Integer, primary_key=True)
    isolate_id = db.Column(db.Integer, db.ForeignKey("culture_isolates.id"),
                           nullable=False, index=True)
    antibiotic_id = db.Column(db.Integer, db.ForeignKey("micro_antibiotics.id"),
                              nullable=False, index=True)
    reading = db.Column(db.String(1), nullable=False)       # S | I | R
    #: The MIC or zone as the laboratory wrote it, if it did.
    value = db.Column(db.String(20))

    isolate = db.relationship("CultureIsolate", back_populates="readings")
    antibiotic = db.relationship("MicroAntibiotic")
