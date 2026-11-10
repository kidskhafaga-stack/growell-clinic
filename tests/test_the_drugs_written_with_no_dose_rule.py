"""The drugs this clinic writes most with no dose by weight behind them
(PLAN_2026-08-08 «تغطية حساب الجرعة»).

From the clinic's own prescriptions, most written first, each with the door
to write its rule. A rule is a clinical number: a doctor writes it, with its
reference — no reference, no rule — and the prescription check reads it at
once.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _world(clinic):
    from app.models import Drug, GenericDrug, Prescription, PrescriptionItem
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        para = GenericDrug(name_ar="باراسيتامول", name_en="Paracetamol", dose_per_kg=15, doses_per_day=4)
        cetir = GenericDrug(name_ar="سيتريزين", name_en="Cetirizine")
        db.session.add_all([para, cetir])
        db.session.flush()
        brand = Drug(trade_name="Zyrtec", generic_id=cetir.id, is_active=True)
        lonely = Drug(trade_name="Mystery Syrup", is_active=True)
        db.session.add_all([brand, lonely])
        db.session.flush()
        rx = Prescription(patient_id=clinic["ids"]["child"], rx_date=local_today())
        db.session.add(rx)
        db.session.flush()
        for name, drug in (("Paracetamol", None), ("Zyrtec", brand), ("Zyrtec", brand),
                           ("Cetirizine", None), ("Mystery Syrup", lonely), ("شراب كحة", None)):
            db.session.add(PrescriptionItem(prescription_id=rx.id, drug_name=name,
                                            drug_id=drug.id if drug else None))
        db.session.commit()
        return {"cetir": cetir.id, "lonely": lonely.id}


def test_the_most_written_without_a_rule_come_first_with_their_door(clinic):
    ids = _world(clinic)
    page = clinic["sign_in"]("doc").get("/prescriptions/dose-gaps").get_data(as_text=True)
    assert "data-dose-gaps" in page
    rows = page.split("data-gap=")[1:]
    assert "generic\"" in rows[0] and "سيتريزين" in rows[0]
    assert "3" in rows[0].split("data-gap-count>", 1)[1][:4], "Zyrtec twice + Cetirizine once"
    assert f"/prescriptions/drugbook/{ids['cetir']}" in rows[0], "the door to write its rule"
    kinds = [r.split('"', 2)[1] for r in rows]
    assert set(kinds) == {"generic", "brand", "free"}
    assert "باراسيتامول" not in page.split("data-dose-gaps", 1)[1], "covered drugs are not listed"
    assert "17" in page.split("data-coverage-pct>", 1)[1][:6], "1 of 6 lines covered"
    assert "data-to-dose-gaps" in clinic["sign_in"]("doc").get("/prescriptions/drugbook").get_data(as_text=True)


def test_a_doctor_writes_the_rule_with_its_reference_and_it_is_covered_at_once(clinic):
    from app.models import GenericDrug

    ids = _world(clinic)
    doc = clinic["sign_in"]("doc")
    doc.post(f"/prescriptions/drugbook/{ids['cetir']}/dose", data={"dose_per_kg": "0.25"})
    with clinic["app"].app_context():
        assert clinic["db"].session.get(GenericDrug, ids["cetir"]).dose_per_kg is None, \
            "no reference, no rule"
    doc.post(f"/prescriptions/drugbook/{ids['cetir']}/dose", data={
        "dose_per_kg": "0.25", "doses_per_day": "1", "max_single_dose_mg": "5",
        "reference": "BNF for Children 2025"})
    with clinic["app"].app_context():
        g = clinic["db"].session.get(GenericDrug, ids["cetir"])
        assert g.dose_per_kg == 0.25 and g.reference == "BNF for Children 2025"
    page = doc.get("/prescriptions/dose-gaps").get_data(as_text=True)
    assert "سيتريزين" not in page.split("data-dose-gaps", 1)[1]


def test_only_a_doctor_or_the_admin_writes_a_rule(clinic):
    from app.models import User

    ids = _world(clinic)
    with clinic["app"].app_context():
        roles = {u.username: u.role for u in User.query.all()}
    other = next((name for name, role in roles.items() if role not in ("doctor", "admin")), None)
    if other is None:
        return
    r = clinic["sign_in"](other).post(f"/prescriptions/drugbook/{ids['cetir']}/dose", data={
        "dose_per_kg": "0.25", "reference": "x"})
    assert r.status_code in (302, 403)
    from app.models import GenericDrug

    with clinic["app"].app_context():
        assert clinic["db"].session.get(GenericDrug, ids["cetir"]).dose_per_kg is None
