"""Nine words used eleven lines at the top of every prescription.

Asked as: why isn't the patient's data on one line — name, age, gender and
weight — and then the complaint and diagnosis, so it is condensed instead of
running down the page.

Measured on the A5 that prompted it: the identity and clinical blocks ran from
y=103 to y=318, 215pt of a 595pt sheet — 36% of the paper spent before the ℞,
and the investigations pushed onto a second page. After: y=150 to y=235, 85pt.
"""
import os
import sys
from datetime import date
from html.parser import HTMLParser

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RX_DATE = date(2026, 8, 16)


def _paper(clinic, weight=12.5, **tpl_kw):
    from app.extensions import db
    from app.models import (GrowthRecord, Patient, Prescription,
                            PrescriptionItem, RxPrintTemplate, User)

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        kid = Patient.query.first()
        kid.allergies = "بنسلين"
        kid.chronic_diseases = "ربو"
        if weight is not None:
            db.session.add(GrowthRecord(patient_id=kid.id, record_date=RX_DATE,
                                        weight_kg=weight))
        rx = Prescription(patient_id=kid.id, doctor_id=doc.id, rx_date=RX_DATE,
                          complaint="كحة وحرارة", diagnosis="التهاب رئوي",
                          diagnosis_code="J18.9")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="Augmentin", printed=True))
        flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                 for f in RxPrintTemplate.BOOLS}
        flags.update(tpl_kw)
        tpl = RxPrintTemplate(name="t", mode="white", page_size="A5",
                              font_size=10, margin_mm=12, top_offset_mm=0,
                              **flags)
        db.session.add(tpl)
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id

    return clinic["sign_in"]("boss").get(
        f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()


class _Runs(HTMLParser):
    """The text of each `.rx-line`, flattened, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.runs = []
        self._buf = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        if self.depth:
            self.depth += 1
        elif "rx-line" in classes:
            self.depth = 1
            self._buf = []

    def handle_endtag(self, tag):
        if not self.depth:
            return
        self.depth -= 1
        if self.depth == 0:
            self.runs.append(" ".join("".join(self._buf).split()))

    def handle_data(self, data):
        if self.depth:
            self._buf.append(data)


def _runs(page):
    parser = _Runs()
    parser.feed(page)
    return parser.runs


# --------------------------------------------------- everything on one run

def test_the_patient_is_one_run_not_a_column_of_pairs(clinic):
    """It was a grid with every label stacked above its own value."""
    page = _paper(clinic)
    runs = _runs(page)

    assert runs, "there is no single-line block on the paper at all"
    assert "info-grid" not in page, \
        "the stacked label-above-value grid is still on the prescription"


def test_name_age_gender_and_weight_are_together(clinic):
    """The four things asked for, in the same run."""
    page = _paper(clinic)
    identity = _runs(page)[0]

    for wanted in ("طفل", "12.5"):
        assert wanted in identity, \
            f"{wanted!r} is not on the patient line: {identity!r}"
    assert "ذكر" in identity or "أنثى" in identity, \
        f"the gender is not on the patient line: {identity!r}"


def test_the_complaint_and_the_diagnosis_share_a_run(clinic):
    """Two headings with a line under each became one line."""
    page = _paper(clinic)
    clinical = _runs(page)[1]

    assert "كحة وحرارة" in clinical, f"no complaint: {clinical!r}"
    assert "التهاب رئوي" in clinical, f"no diagnosis: {clinical!r}"
    assert "J18.9" in clinical, f"the code fell off: {clinical!r}"


def test_the_weight_is_printed_once(clinic):
    """It moved up to the patient line; leaving it below prints it twice."""
    page = _paper(clinic)

    assert page.count("12.5") == 1, \
        f"the weight appears {page.count('12.5')} times on one prescription"


# ---------------------------------------- and the switches still do their job

def test_turning_the_weight_off_removes_it(clinic):
    page = _paper(clinic, show_weight=False)

    assert "12.5" not in page, "the weight printed on a template with it off"


def test_turning_the_patient_block_off_removes_the_line(clinic):
    page = _paper(clinic, show_patient=False)

    assert "طفل" not in page, "the patient printed on a template with it off"


def test_the_weight_does_not_vanish_with_the_patient_block(clinic):
    """The edge the move created, and the one that would have hurt.

    A template with the patient block off and the weight on would have
    dropped the number a mg/kg dose was worked out from — silently, because
    the weight now travels with the patient line. It falls back to the
    warning band, which is where it used to live.
    """
    page = _paper(clinic, show_patient=False, show_weight=True)

    assert "12.5" in page, \
        "the weight disappeared with the patient block it was moved into"


def test_the_allergy_still_speaks_when_the_file_is_empty(clinic):
    """Unchanged, and asserted because the band around it was rebuilt.

    A blank cannot be read: nobody looking at one can tell a child with no
    allergies from a child nobody asked.
    """
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        Patient.query.first().allergies = ""
        db.session.commit()

    page = _paper(clinic)

    assert "الحساسية" in page, "the allergy line went silent"


def test_the_chronic_condition_still_prints_beside_it(clinic):
    page = _paper(clinic)

    assert "ربو" in page, "the chronic condition fell out of the rebuilt band"


def test_a_patient_with_no_weight_recorded_prints_no_weight_label(clinic):
    """An empty "Weight:" is worse than no weight line."""
    page = _paper(clinic, weight=None)
    identity = _runs(page)[0]

    assert "كجم" not in identity, \
        f"an empty weight label printed on the patient line: {identity!r}"
