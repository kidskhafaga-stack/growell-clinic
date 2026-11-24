"""«تبدأ بأنهي تطعيم؟» — the optional vaccines ranked (SMART_PATTERNS ج-٥ أ).

The vaccination unit's program ranked what to offer a child with a score,
tried on real data; these hold the score as it was carried over:

* the age: right now 50 · passed but still allowed 35 · later 10;
* a brother or sister **linked in the family file** who had it +30 — a
  guess from the name is never a reason here;
* «اللي أخدوا A عندنا أخدوا X» up to +25, only for a pair kept by its
  conditions (A in 150 children or more, X in 35 % of them, 1.5 × usual);
* high from 75, medium from 55; national and on-demand vaccines, ones taken
  and ones already agreed are not offered;
* the parents' message has the sibling line only for a linked sibling, and
  the person sending it can change it;
* the pattern is counted once a day, and only where vaccinations run.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _vaccine(db, code, months, mandatory=False):
    from app.models import Vaccine, VaccineBrand, VaccineBrandDose

    v = Vaccine(code=code, name_ar=code, name_en=code, is_mandatory=mandatory)
    db.session.add(v)
    db.session.flush()
    b = VaccineBrand(vaccine_id=v.id, name=code + " brand", price=500)
    db.session.add(b)
    db.session.flush()
    db.session.add(VaccineBrandDose(brand_id=b.id, dose_number=1, age_months=months))
    return v, b


def _give(db, patient_id, v, b, on, doctor_id):
    from app.models import PatientVaccine

    db.session.add(PatientVaccine(patient_id=patient_id, vaccine_id=v.id, brand_id=b.id,
                                  dose_number=1, given_date=on, doctor_id=doctor_id))


@pytest.fixture()
def ranked(clinic):
    """A child of 22 months with a phone, linked in one family to an older
    sister who had hepatitis A; the child had rotavirus. Rotavirus was given
    here to 150 children, 120 of whom had the pneumococcal too; 200 more had
    only polio. Hepatitis A falls due at 22 months, varicella at 48."""
    from app.models import Family, Patient
    from app.utils.clock import local_today
    from app.utils.vaccines import add_months

    today = local_today()
    with clinic["app"].app_context():
        db = clinic["db"]
        doc = clinic["ids"]["doctor"]
        from app.models import Vaccine, VaccineBrand

        pcv = db.session.get(Vaccine, clinic["ids"]["pcv"])
        pcv_b = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        opv = db.session.get(Vaccine, clinic["ids"]["opv"])
        opv_b = db.session.get(VaccineBrand, clinic["ids"]["gov_brand"])
        rota, rota_b = _vaccine(db, "ROTA", 2)
        hepa, hepa_b = _vaccine(db, "HEPA", 22)
        var, var_b = _vaccine(db, "VAR", 48)
        fam = Family(family_name="عيلة")
        db.session.add(fam)
        db.session.flush()
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = add_months(today, -22)
        child.family_id = fam.id
        child.own_phone = "01001234567"
        sister = Patient(patient_number="P2", full_name="مريم أحمد", gender="female",
                         date_of_birth=add_months(today, -60), family_id=fam.id, is_active=True)
        db.session.add(sister)
        db.session.flush()
        _give(db, sister.id, hepa, hepa_b, add_months(today, -30), doc)
        _give(db, child.id, rota, rota_b, add_months(today, -20), doc)
        old = date(2024, 1, 1)
        for i in range(350):
            p = Patient(patient_number=f"Q{i}", full_name=f"طفل {i}", gender="male",
                        date_of_birth=date(2023, 1, 1), is_active=True)
            db.session.add(p)
            db.session.flush()
            if i < 150:
                _give(db, p.id, rota, rota_b, old, doc)
                if i < 120:
                    _give(db, p.id, pcv, pcv_b, old, doc)
            else:
                _give(db, p.id, opv, opv_b, old, doc)
        db.session.commit()
        clinic["ids"].update(rota=rota.id, hepa=hepa.id, var=var.id, sister=sister.id)
    return clinic


def _refresh(c):
    from app.utils import vaccine_suggest as vs

    with c["app"].app_context():
        n = vs.refresh_patterns()
        c["db"].session.commit()
        return n


def _rank(c):
    from app.models import Patient
    from app.utils import vaccine_suggest as vs
    from app.utils.vaccines import patient_plan

    with c["app"].app_context():
        child = c["db"].session.get(Patient, c["ids"]["child"])
        got = vs.for_patient(child, patient_plan(child))
        return {s["vaccine"].code: s for s in got}, [s["vaccine"].code for s in got]


def test_the_clinic_s_pattern_and_its_conditions(ranked):
    from app.models import VaccinePattern

    assert _refresh(ranked) >= 1
    with ranked["app"].app_context():
        row = VaccinePattern.query.filter_by(a_vaccine_id=ranked["ids"]["rota"],
                                             x_vaccine_id=ranked["ids"]["pcv"]).one()
        # 151 had rotavirus (the child too), 120 of them the pneumococcal.
        assert (row.with_a, row.with_both) == (151, 120)
        # Polio, given to 200, is with nothing at 35 % — no pair from it.
        assert VaccinePattern.query.filter_by(
            a_vaccine_id=ranked["ids"]["opv"]).count() == 0


def test_the_score(ranked):
    _refresh(ranked)
    got, order = _rank(ranked)
    # Hepatitis A: right now 50 + the sister linked in the family file 30.
    assert (got["HEPA"]["score"], got["HEPA"]["priority"], got["HEPA"]["age"]) == (80, "high", "now")
    # Pneumococcal: passed but allowed 35 + 79 % of the rotavirus children 20.
    assert (got["PCV"]["score"], got["PCV"]["pattern_points"], got["PCV"]["priority"]) == \
        (55, 20, "medium")
    assert (got["VAR"]["score"], got["VAR"]["priority"]) == (10, "low")
    assert order == ["HEPA", "PCV", "VAR"], "highest first"
    assert "OPV" not in got, "the national schedule is the government unit's"
    assert "ROTA" not in got, "already had"


def test_no_family_link_no_sibling_points(ranked):
    from app.models import Patient

    _refresh(ranked)
    with ranked["app"].app_context():
        ranked["db"].session.get(Patient, ranked["ids"]["sister"]).family_id = None
        ranked["db"].session.commit()
    got, _ = _rank(ranked)
    assert got["HEPA"]["score"] == 50 and not got["HEPA"]["siblings"]


def test_the_page_and_the_message(ranked):
    _refresh(ranked)
    page = ranked["sign_in"]("doc").get(f"/vaccinations/{ranked['ids']['child']}").get_data(as_text=True)
    assert 'data-vsuggest-row="HEPA" data-priority="high" data-score="80"' in page
    assert 'data-vsuggest-row="PCV" data-priority="medium"' in page
    assert "data-vsuggest-sibling" in page and "مريم أحمد" in page
    assert "data-vsuggest-pattern" in page
    # The message rides in a single-quoted attribute; its quotes stay inside.
    assert "x-data='{ \"open\": false, \"text\": \"" in page
    assert "https://wa.me/201001234567?text=" in page
    # The sibling line in the parents' message, for a linked sister only.
    assert "ومريم أخدت HEPA عندنا قبل كده" in page
    assert "أخدته مريم أحمد" in page, "her, not him"
    var_row = page.split('data-vsuggest-row="VAR"', 1)[1]
    assert "أخدت VAR" not in var_row, "no sister line where she did not have it"


def test_an_agreed_vaccine_is_not_offered_again(ranked):
    _refresh(ranked)
    doc = ranked["sign_in"]("doc")
    doc.post(f"/vaccinations/{ranked['ids']['child']}/plan/add",
             data={"vaccine_id": ranked["ids"]["hepa"]})
    page = doc.get(f"/vaccinations/{ranked['ids']['child']}").get_data(as_text=True)
    assert 'data-vsuggest-row="HEPA"' not in page


def test_counted_once_a_day_where_vaccinations_run(ranked):
    from app.models import Setting, VaccinePattern
    from app.utils import vaccine_suggest as vs

    with ranked["app"].app_context():
        assert vs.maybe_refresh() is True
        assert VaccinePattern.query.count() >= 1
        assert vs.maybe_refresh() is False, "once a day"
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:vaccinations", "0")
        Setting.set(vs.TICK, "")
        ranked["db"].session.commit()
        assert vs.maybe_refresh() is False, "no vaccinations, no count"
