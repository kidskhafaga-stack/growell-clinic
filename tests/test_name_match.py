"""Offering the clinic's own services and doctors, not just its vaccines.

The linking screen already matched the file's vaccine names against the
catalogue. Two of the three columns it links were still doing something else:

* the **service** name was matched against nothing at all — every non-vaccine
  row came back as "a plain service", which on the real export is كشف and
  إستشارة, 7,476 rows of work the clinic already has priced and commissioned;
* the **doctor** name was matched by exact text, so the clinic's own
  "د. أحمد" and the file's "د/ أحمد" were two different people and neither
  found the other.

Both are now the same scorer as the vaccines, which is the point: one file, one
idea of what "the same name" means. The rule the whole import runs on is
unchanged — **it proposes, the clinic confirms**. A name nothing matches is
still offered as "none of these", because the alternative is a matcher that
invents a service out of a typo.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _services(clinic, *names):
    from app.utils.name_match import suggest_services

    with clinic["app"].app_context():
        return suggest_services(list(names))


def _doctors(clinic, *names):
    from app.utils.name_match import suggest_doctors

    with clinic["app"].test_request_context("/"):
        return suggest_doctors(list(names))


# =================================================== the file's own service ==
def test_the_exact_service_name_is_found(clinic):
    """The commonest case by a distance: the old program and this one call the
    consultation the same thing."""
    hits = _services(clinic, "كشف")["كشف"]
    assert hits
    assert hits[0]["service_id"] == clinic["ids"]["exam"]


def test_a_definite_article_does_not_hide_the_service(clinic):
    """"الكشف" and "كشف" are one service written twice."""
    hits = _services(clinic, "الكشف")["الكشف"]
    assert hits and hits[0]["service_id"] == clinic["ids"]["exam"]


def test_a_longer_wording_still_finds_it(clinic):
    """Old programs pad a name — "كشف عيادة", "كشف - عام". The extra words
    explain nothing, and must not stop the part that does."""
    hits = _services(clinic, "كشف عيادة")["كشف عيادة"]
    assert hits and hits[0]["service_id"] == clinic["ids"]["exam"]


def test_the_spellings_of_one_arabic_word_are_one_service(clinic):
    """"جلسه تنفس" against a catalogue that writes "جلسة تنفس" — the same
    folding the rest of the import runs on."""
    hits = _services(clinic, "جلسه تنفس")["جلسه تنفس"]
    assert hits and hits[0]["service_id"] == clinic["ids"]["nebul"]


def test_a_name_nothing_matches_proposes_nothing(clinic):
    """An empty answer is the honest one. A matcher that always produces a
    candidate is one whose candidates mean nothing."""
    assert _services(clinic, "زيارة منزلية")["زيارة منزلية"] == []


def test_an_inactive_service_is_not_offered(clinic):
    """Retiring a service is a decision. Re-attaching ten years of history to
    it would quietly undo that decision on the clinic's behalf."""
    from app.models import Service

    with clinic["app"].app_context():
        row = Service.query.filter_by(id=clinic["ids"]["nebul"]).first()
        row.is_active = False
        clinic["db"].session.commit()
    assert _services(clinic, "جلسة تنفس")["جلسة تنفس"] == []


def test_a_confident_match_says_so(clinic):
    hits = _services(clinic, "كشف")["كشف"]
    assert hits[0]["confidence"] in ("high", "medium")


# ========================================================== and its doctors ==
def test_a_title_in_front_of_the_name_is_ignored(clinic):
    """"د/ أحمد" is the clinic's own "د. أحمد". The title is on every row of
    the file and on none of the clinic's users — scored, it would make every
    doctor look like every other."""
    hits = _doctors(clinic, "د/ أحمد")["د/ أحمد"]
    assert hits and hits[0]["user_id"] == clinic["ids"]["doctor"]


def test_the_spellings_of_the_name_are_folded_too(clinic):
    hits = _doctors(clinic, "احمد")["احمد"]
    assert hits and hits[0]["user_id"] == clinic["ids"]["doctor"]


def test_only_people_who_see_patients_are_offered(clinic):
    """The reception and the accountant are staff, not the doctor on a
    vaccination row."""
    hits = _doctors(clinic, "الاستقبال")["الاستقبال"]
    assert all(h["user_id"] != clinic["ids"]["desk"] for h in hits)


def test_an_unknown_doctor_proposes_nobody(clinic):
    """Somebody who left before this program existed. The row keeps its text
    and the clinic decides — inventing a user would be worse."""
    assert _doctors(clinic, "د. سعاد")["د. سعاد"] == []


# ================================================= one proposal per file row ==
def _best(clinic, *names):
    from app.blueprints.patients.routes import _best_link
    from app.utils.name_match import suggest_services
    from app.utils.vaccine_match import suggest_all

    values = list(names)
    with clinic["app"].app_context():
        return _best_link(values, suggest_all(values), suggest_services(values))


def test_a_service_name_proposes_the_service(clinic):
    assert _best(clinic, "كشف")["كشف"][0] == f"service:{clinic['ids']['exam']}"


def test_a_vaccine_name_proposes_the_brand(clinic):
    choice = _best(clinic, "Prevenar - PCV 13")["Prevenar - PCV 13"][0]
    assert choice == f"brand:{clinic['ids']['brand']}"


def test_a_tie_goes_to_the_vaccine(clinic):
    """A vaccination row carries a dose number and a course. Linking it to a
    "vaccination fee" service would price it correctly and still leave the
    child's schedule unaware the dose ever happened."""
    from app.blueprints.patients.routes import _best_link

    vaccine = {"x": [{"brand_id": 7, "score": 4, "confidence": "high"}]}
    service = {"x": [{"service_id": 9, "score": 4, "confidence": "high"}]}
    assert _best_link(["x"], vaccine, service)["x"][0] == "brand:7"


def test_a_higher_scoring_service_wins(clinic):
    from app.blueprints.patients.routes import _best_link

    vaccine = {"x": [{"brand_id": 7, "score": 2, "confidence": "low"}]}
    service = {"x": [{"service_id": 9, "score": 6, "confidence": "high"}]}
    assert _best_link(["x"], vaccine, service)["x"] == ("service:9", "high")


def test_a_name_nothing_matches_gets_no_proposal(clinic):
    assert "زيارة منزلية" not in _best(clinic, "زيارة منزلية")


# ================================================================= the screen ==
def _link_screen(client):
    """Push a one-row file through the wizard and return the linking screen."""
    import io
    import re
    from datetime import date

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["كود المريض", "التاريخ", "الخدمة", "السعر", "الطبيب"])
    ws.append(["P1", date(2024, 1, 1), "كشف", 200, "د/ أحمد"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    reply = client.post("/patients/import/history", data={"file": (buf, "h.xlsx")},
                        content_type="multipart/form-data")
    token = re.search(r'name="token" value="([0-9a-f]+)"',
                      reply.get_data(as_text=True)).group(1)
    return client.post("/patients/import/history/link", data={
        "token": token, "col_patient_code": 0, "col_service_date": 1,
        "col_service_name": 2, "col_price": 3, "col_doctor_name": 4,
    }).get_data(as_text=True)


def test_the_screen_offers_both_catalogues(boss, clinic):
    """One select per row, holding the services and the vaccines — because the
    file holds both and the person reading it does not know in advance which
    this row is."""
    body = _link_screen(boss)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.group_services") in body
        assert t("history_import.group_vaccines") in body


def test_the_screen_preselects_the_service_it_recognised(boss, clinic):
    """The whole point of the screen: the clinic reads down it and changes what
    it disagrees with, rather than filling in every row by hand."""
    body = _link_screen(boss)
    assert f'value="service:{clinic["ids"]["exam"]}" selected' in body


def test_the_screen_preselects_the_doctor_it_recognised(boss, clinic):
    """"د/ أحمد" in the file is the clinic's own "د. أحمد"."""
    body = _link_screen(boss)
    assert f'value="{clinic["ids"]["doctor"]}" selected' in body


def test_both_languages_carry_the_group_labels(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("group_services", "group_vaccines"):
            assert data["history_import"].get(key), f"{lang}.{key}"


# =============================================== and the link is written down ==
def test_a_confirmed_service_link_resolves(clinic):
    from app.blueprints.patients.routes import _resolved_services

    with clinic["app"].app_context():
        out = _resolved_services({"كشف": f"service:{clinic['ids']['exam']}"})
    assert out == {"كشف": clinic["ids"]["exam"]}


def test_a_brand_choice_is_not_read_as_a_service(clinic):
    from app.blueprints.patients.routes import _resolved_services

    with clinic["app"].app_context():
        assert _resolved_services({"x": "brand:3"}) == {}


def test_a_deleted_service_is_dropped_rather_than_left_dangling(clinic):
    """A mapping saved against a service somebody has since removed would write
    a reference into ten years of history that points at nothing."""
    from app.blueprints.patients.routes import _resolved_services

    with clinic["app"].app_context():
        assert _resolved_services({"x": "service:99999"}) == {}
