"""The program makes its own PDF files — «ضيف مكتبة PDF» (``utils/pdf``).

The first is the payer's approval form (CONTRACTS_PLAN.md ع-٥): it went to
the payer as an HTML page; now it goes as a PDF, drawn with the same facts in
the same millimetres. Where the library is missing on a computer, the page
goes as before instead of the sending failing.
"""
import json

import pytest

from app.utils import pdf


@pytest.fixture()
def form(clinic):
    from app.models import PatientCoverage, PayerEntity, PayerForm

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة النيل للتأمين", entity_type="insurance", is_active=True)
        db.session.add(payer)
        db.session.flush()
        db.session.add(PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                                       membership_number="NL-7781", is_active=True))
        row = PayerForm(payer_id=payer.id, name="استمارة العيادات", fields=json.dumps([
            {"key": "patient_name", "x": 20, "y": 30, "w": 80, "size": 11, "align": "right"},
            {"key": "membership_number", "x": 120, "y": 30, "w": 50, "size": 11, "align": "left"},
            {"key": "date", "x": 20, "y": 60, "w": 40, "size": 10, "align": "center"}]))
        db.session.add(row)
        db.session.commit()
        clinic["ids"].update(form=row.id, payer=payer.id)
    return clinic


def test_numbers_stay_left_to_right_inside_arabic():
    assert pdf.isolate_numbers("تاريخ 2026-11-01") == "تاريخ ⁦2026-11-01⁩"
    assert pdf.isolate_numbers("رقم 7") == "رقم 7", "one digit has no order to keep"
    assert pdf.isolate_numbers("") == ""


def test_the_library_and_the_font_are_here():
    assert pdf.available(), "fpdf2 is in requirements.txt"
    doc = pdf.new(148, 210)
    pdf.text_box(doc, 10, 10, 100, 12, "محمد أحمد — NL-7781 — 2026-11-01")
    data = pdf.output(doc)
    assert data.startswith(b"%PDF") and b"Cairo" in data


def test_the_form_as_a_pdf_with_the_facts_in_their_places(form, monkeypatch):
    from app.models import Patient, PayerForm
    from app.utils import payer_forms as pf

    drawn = []
    real = pdf.text_box
    monkeypatch.setattr(pdf, "text_box", lambda doc, x, y, w, size, text, align="right", **k:
                        (drawn.append((x, y, w, text, align)), real(doc, x, y, w, size, text,
                                                                    align=align))[1])
    with form["app"].test_request_context("/"):
        row = form["db"].session.get(PayerForm, form["ids"]["form"])
        child = form["db"].session.get(Patient, form["ids"]["child"])
        values = pf.facts(child, row.payer)
        data = pf.page_pdf(row, values)
    assert data.startswith(b"%PDF")
    assert (120, 30, 50, "NL-7781", "left") in drawn
    assert (20, 30, 80, values["patient_name"], "right") in drawn and values["patient_name"]


def test_the_scan_goes_behind_on_plain_paper(form, tmp_path, monkeypatch):
    from PIL import Image

    from app.models import PayerForm
    from app.utils import payer_forms as pf
    from app.utils import uploads

    monkeypatch.setattr(uploads, "docs_dir", lambda: str(tmp_path))
    Image.new("RGB", (60, 80), (250, 240, 200)).save(tmp_path / "blank.png")
    with form["app"].test_request_context("/"):
        row = form["db"].session.get(PayerForm, form["ids"]["form"])
        row.background = "blank.png"
        values = {"patient_name": "س"}
        row.print_background = False
        plain = pf.page_pdf(row, values)
        row.print_background = True
        behind = pf.page_pdf(row, values)
    assert b"/Subtype /Image" not in plain and b"/Subtype /Image" in behind


def test_saved_from_the_print_and_the_approvals(form):
    boss = form["sign_in"]("boss")
    fid, vid = form["ids"]["form"], form["ids"]["visit"]
    page = boss.get(f"/payer-forms/{fid}/print?visit={vid}").get_data(as_text=True)
    assert f'/payer-forms/{fid}/pdf?visit={vid}' in page and "data-form-pdf" in page
    got = boss.get(f"/payer-forms/{fid}/pdf?visit={vid}")
    assert got.status_code == 200 and got.mimetype == "application/pdf"
    assert got.data.startswith(b"%PDF")
    # Who may print may save; nobody signed in may not.
    assert form["app"].test_client().get(f"/payer-forms/{fid}/pdf").status_code in (302, 401)


def test_without_the_library_the_page_goes_as_before(form, monkeypatch):
    from app.models import PayerForm
    from app.utils import payer_forms as pf

    monkeypatch.setattr(pdf, "available", lambda: False)
    with form["app"].test_request_context("/"):
        row = form["db"].session.get(PayerForm, form["ids"]["form"])
        data, filename, mime = pf.attachment(row, {"membership_number": "NL-7781"})
    assert (filename, mime) == ("approval-request.html", "text/html") and b"NL-7781" in data
    boss = form["sign_in"]("boss")
    fid = form["ids"]["form"]
    assert "data-form-pdf" not in boss.get(f"/payer-forms/{fid}/print").get_data(as_text=True)
    assert boss.get(f"/payer-forms/{fid}/pdf").status_code == 404
