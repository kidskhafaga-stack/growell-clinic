"""Each trade name's age limit, read from its own label — or said not read.

IMPROVEMENTS_BACKLOG ٠.١ left the brands whose leaflet «does not say» a
ceiling with none, on purpose: a number invented to tidy the screen is a
clinical decision the program has no right to. What it asked for was a
number «from a published source under its own name».

So the labels were read — the EMA product information and the FDA package
insert, on 16 November 2026 — and each brand now carries what its label says:

* **a ceiling**, where the label writes one: Menactra, «9 months through 55
  years of age»;
* **«no upper age»**, where the label's indication runs open-ended («from 2
  months of age and older», «adults ≥18 years of age and the elderly»). That
  is a fact read, not a blank — and it is different from never having looked;
* **both labels, and no number**, where the EU and the US disagree (Menveo,
  Bexsero): picking one silently is the thing this file exists to stop.

Every other brand is named below with why its label was not read, so a gap
is visible here and not remembered.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import pytest  # noqa: E402
CATALOGUE = os.path.join(HERE, "..", "app", "data", "egypt_vaccines.json")

#: Not read, and why — each one is a gap someone can close with the leaflet.
NOT_READ = {
    # The national programme's products carry no one trade label: the
    # ministry's schedule is their authority (IMPROVEMENTS_BACKLOG ٠.٢).
    ("BCG", "حكومي"), ("HBV0", "حكومي"), ("OPV", "حكومي"), ("IPV", "حكومي"),
    ("MEASLES", "حكومي"), ("MMR", "حكومي"), ("VIT_A", "حكومي"),
    # Authorised nationally in Europe, not by EMA, and not sold in the US:
    # no central label reachable from here.
    ("VARICELLA", "Varilrix"), ("FLU", "Vaxigrip"), ("FLU", "Influvac Tetra"),
    ("PPSV23", "Pneumo 23"), ("RABIES", "Verorab"),
    ("YELLOWFEVER", "Stamaril"), ("MENACWY", "Mencevax"),
    # WHO-prequalified; its label is on WHO's prequalification site.
    ("TYPHOID", "Typbar TCV"),
}


def _brands():
    with open(CATALOGUE, encoding="utf-8") as fh:
        data = json.load(fh)
    for vaccine in data["vaccines"]:
        for brand in vaccine["brands"]:
            yield vaccine["code"], brand


def _brand(code, name):
    return next(b for c, b in _brands() if (c, b["name"]) == (code, name))


def test_every_brand_has_a_ceiling_a_label_read_or_a_named_gap():
    for code, brand in _brands():
        key = (code, brand["name"])
        if brand.get("max_age_final_dose_days"):
            continue
        assert brand.get("label_age") or key in NOT_READ, \
            f"{key}: no ceiling, no label read, and not named as a gap"
        # A brand both read and listed as not read is one of them wrong.
        assert not (brand.get("label_age") and key in NOT_READ), key


def test_a_label_read_says_where_and_when_and_quotes_it():
    read = [(c, b) for c, b in _brands() if b.get("label_age")]
    assert len(read) == 14
    for code, brand in read:
        label = brand["label_age"]
        assert label["url"].startswith(("https://www.ema.europa.eu/",
                                        "https://www.fda.gov/",
                                        "https://dailymed.nlm.nih.gov/")), code
        assert label["read_on"] == "2026-11-16"
        assert len(label["quote"]) > 20, (code, brand["name"])


def test_menactra_stops_where_its_label_does():
    menactra = _brand("MENACWY", "Menactra")
    assert "9 months through 55 years of age" in menactra["label_age"]["quote"]
    # «through 55» — up to the day before the 56th birthday, the same way
    # Priorix Tetra's «up to 12 inclusive» is written.
    assert menactra["max_age_final_dose_days"] == round(56 * 365.25)
    tetra = _brand("MMRV", "Priorix Tetra")
    assert tetra["max_age_final_dose_days"] == round(13 * 365.25)


@pytest.mark.parametrize("name", ["Menveo", "Bexsero"])
def test_where_the_labels_disagree_no_number_is_picked(name):
    code = "MENB" if name == "Bexsero" else "MENACWY"
    brand = _brand(code, name)
    label = brand["label_age"]
    assert brand.get("max_age_final_dose_days") is None
    assert label["upper"] is None                         # the EU label
    assert "through" in label["other_label"]["quote"]     # the US label
    assert "disagree" in label["note"]


def test_open_ended_labels_are_read_as_no_upper_age():
    for code, name, words in (
            ("PCV", "Prevenar 13", "the elderly"),
            ("PCV", "Prevenar 20", "18 years of age and older"),
            ("MENACWY", "Nimenrix", "from the age of 6 weeks"),
            ("VARICELLA", "Varivax", "12 months of age and older"),
            ("RABIES", "Rabipur", "in all age groups"),
            ("CHOLERA", "Dukoral", "from 2 years of age")):
        brand = _brand(code, name)
        assert words in brand["label_age"]["quote"], name
        assert brand["label_age"]["upper"] is None, name
        assert not brand.get("max_age_final_dose_days"), name


def test_the_ceiling_reaches_the_clinic_on_the_next_seed(clinic):
    """A clinic seeded before this gets Menactra's ceiling — and a clinic
    that wrote its own keeps it."""
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand
    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
        menactra = VaccineBrand.query.filter_by(name="Menactra").first()
        assert menactra.max_age_final_dose_days == round(56 * 365.25)
        menactra.max_age_final_dose_days = 7000
        db.session.commit()
        seed_vaccines()
        db.session.commit()
        assert db.session.get(VaccineBrand, menactra.id) \
            .max_age_final_dose_days == 7000
        bexsero = (VaccineBrand.query.join(Vaccine)
                   .filter(Vaccine.code == "MENB",
                           VaccineBrand.name == "Bexsero").first())
        assert bexsero.max_age_final_dose_days is None


# ------------------------------------------------------------------------
# The clinic's own label — the owner's decision, 16 November 2026:
# «امشي على النشرة الأوروبية اكتب الاثنين النشرتين وخلى الديفولت الاوربية
# وينفع اي مستشفى تغير او عيادة حسب النشرة المعتمده لديها او تقدر تعدل ولما
# يعدل يقول هل حصل تعديل فى النشرة ولا ده تعديل خاص بالعيادة او المستشفى»


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db
    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
    return clinic


def _db_brand(c, code, name):
    from app.models import Vaccine, VaccineBrand

    with c["app"].app_context():
        row = (VaccineBrand.query.join(Vaccine)
               .filter(Vaccine.code == code, VaccineBrand.name == name)
               .first())
        return {"id": row.id, "ceiling": row.max_age_final_dose_days,
                "choice": row.age_label_choice, "kind": row.age_change_kind,
                "note": row.age_change_note, "by": row.age_changed_by}


def _post(c, who, brand_id, **form):
    return c["sign_in"](who).post(
        f"/vaccinations/manage/brand/{brand_id}/age-limit", data=form)


def test_the_eu_label_is_the_default_and_both_are_written(seeded):
    from app.utils.vaccine_labels import days_through

    for code, name, us in (("MENACWY", "Menveo", 55), ("MENB", "Bexsero", 25)):
        brand = _brand(code, name)
        assert brand["label_age"]["label"] == "EMA SmPC"
        assert brand["label_age"]["upper_days"] is None
        assert brand["label_age"]["other_label"]["upper_days"] == \
            days_through(us)
        assert "Default: the EU label" in brand["label_age"]["note"]
    page = seeded["sign_in"]("doc").get("/vaccinations/manage") \
        .get_data(as_text=True)
    assert 'data-age-limit="default" data-age-ceiling=""' in page
    assert "data-age-labels-disagree" in page
    assert "BEXSERO is approved for use in individuals aged 10 through 25" \
        in page
    assert "data-age-limit-form" in page


def test_a_clinic_adopts_the_other_label(seeded):
    from app.models import ActivityLog
    from app.utils.vaccine_labels import days_through

    bexsero = _db_brand(seeded, "MENB", "Bexsero")
    _post(seeded, "doc", bexsero["id"], choice="other")
    got = _db_brand(seeded, "MENB", "Bexsero")
    assert (got["ceiling"], got["choice"], got["kind"]) == \
        (days_through(25), "other", "adopted")
    assert got["by"] == seeded["ids"]["doctor"]
    with seeded["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="vaccine.brand_age_limit").count() == 1
    # And back to the default, which has no upper age.
    _post(seeded, "doc", bexsero["id"], choice="default")
    assert _db_brand(seeded, "MENB", "Bexsero")["ceiling"] is None


def test_its_own_number_must_say_label_changed_or_clinics_own(seeded):
    from app.utils.vaccine_labels import days_through

    menveo = _db_brand(seeded, "MENACWY", "Menveo")
    # Not said which — refused.
    _post(seeded, "boss", menveo["id"], choice="own", years="18",
          note="لجنة الأدوية")
    # Said which, but no words — refused.
    _post(seeded, "boss", menveo["id"], choice="own", years="18",
          kind="clinic_own", note="")
    assert _db_brand(seeded, "MENACWY", "Menveo")["choice"] is None
    _post(seeded, "boss", menveo["id"], choice="own", years="18",
          kind="clinic_own", note="لجنة الأدوية في المستشفى")
    got = _db_brand(seeded, "MENACWY", "Menveo")
    assert (got["ceiling"], got["kind"], got["note"]) == \
        (days_through(18), "clinic_own", "لجنة الأدوية في المستشفى")
    page = seeded["sign_in"]("boss").get("/vaccinations/manage") \
        .get_data(as_text=True)
    assert "تعديل خاص بالعيادة / المستشفى" in page
    assert "لجنة الأدوية في المستشفى" in page


def test_a_newer_label_with_no_upper_age_survives_a_reseed(seeded):
    """«No upper age» is blank in the column — and blank is what a re-seed
    fills. Once the clinic has said it, the catalogue does not undo it."""
    from app.extensions import db
    from app.utils.vaccines import seed_vaccines

    menactra = _db_brand(seeded, "MENACWY", "Menactra")
    assert menactra["ceiling"] == round(56 * 365.25)
    _post(seeded, "doc", menactra["id"], choice="own", years="",
          kind="label_changed", note="نشرة العلبة ٢٠٢٦ من غير سن أقصى")
    with seeded["app"].app_context():
        seed_vaccines()
        db.session.commit()
    got = _db_brand(seeded, "MENACWY", "Menactra")
    assert (got["ceiling"], got["kind"]) == (None, "label_changed")


def test_only_a_prescriber_sets_it(seeded):
    bexsero = _db_brand(seeded, "MENB", "Bexsero")
    resp = _post(seeded, "desk", bexsero["id"], choice="other")
    assert resp.status_code in (302, 403, 404)
    assert _db_brand(seeded, "MENB", "Bexsero")["choice"] is None
    page = seeded["sign_in"]("desk").get("/vaccinations/manage")
    assert "data-age-limit-form" not in page.get_data(as_text=True)
