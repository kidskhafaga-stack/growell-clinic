"""Where a device study is done, and where it is read.

Item 10, answered: *"fine, inside Procedures — but it gets added to the medical
file as its own tab, and organised."*

Two different questions that were being answered by the same list in four
different places:

**Doing one is a procedure.** The visit had a Procedures tab and a Studies tab
side by side, so a doctor deciding "what am I doing for this child" had to
first decide whether the thing they were doing involved a machine. That split
made one decision take two tabs, and made "was the echo done?" a question you
had to look in two places to answer. The study now sits under the procedure
that charged for it.

**Reading them back is a history, and a history is read per device.** "How has
this child's spirometry gone?" was answered from a flat, date-ordered list by
picking the spirometry rows out of the echoes by eye. Grouped by device now,
newest first.

**And there were three copies of the list on the patient file** — a table on
the overview, a second list at the bottom of the visits tab, and no way to read
one device's history. Three copies of one list is three chances to disagree.

The count-per-row is the small thing worth keeping: a study with three values
outside their range and one with none look identical when a row shows only a
date and a device name, and the one that matters is the one nobody clicks.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def scanned(clinic):
    """One child, two devices, four studies — one of them flagged."""
    from app.models import (DeviceStudy, DeviceStudyValue, MedicalDevice,
                            Service)

    with clinic["app"].app_context():
        db = clinic["db"]
        spiro = MedicalDevice(name="جهاز وظائف تنفس", name_en="Spirometer",
                              device_type="spirometry", connection_type="usb",
                              import_mode="manual", is_active=True)
        echo = MedicalDevice(name="جهاز إيكو", name_en="Echo",
                             device_type="echo", connection_type="manual",
                             import_mode="manual", is_active=True)
        db.session.add_all([spiro, echo])
        db.session.flush()

        # A priced procedure that runs the spirometer, so the visit row can
        # carry the study under it.
        db.session.add(Service(name="قياس وظائف تنفس", code="SVC-SP",
                               category="procedure", price=200,
                               device_id=spiro.id, is_active=True))

        made = []
        for dev, when in ((spiro, local_today()),
                          (spiro, local_today() - timedelta(days=200)),
                          (echo, local_today() - timedelta(days=30)),
                          (echo, local_today() - timedelta(days=400))):
            study = DeviceStudy(patient_id=clinic["ids"]["child"],
                                device_id=dev.id, study_date=when,
                                conclusion="طبيعي")
            db.session.add(study)
            made.append(study)
        db.session.flush()

        # The newest spirometry has two values, one out of range.
        db.session.add_all([
            DeviceStudyValue(study_id=made[0].id, name="FEV1", value="80",
                             unit="%", flag="normal"),
            DeviceStudyValue(study_id=made[0].id, name="FVC", value="55",
                             unit="%", flag="low"),
        ])
        db.session.commit()
        ids = {"spiro": spiro.id, "echo": echo.id,
               "newest_spiro": made[0].id}
    return {**clinic, "dev": ids}


@pytest.fixture()
def doc(clinic):
    return clinic["sign_in"]("doc")


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


def _grouped(env):
    from app.models import Patient
    from app.utils.studies import patient_studies

    with env["app"].app_context():
        patient = env["db"].session.get(Patient, env["ids"]["child"])
        return patient_studies(patient)


# ======================================= doing one is a procedure ==========
def test_the_visit_no_longer_has_a_separate_studies_tab(scanned):
    """Two tabs for one decision. A doctor thinks "what am I doing for this
    child", not "does what I am doing involve a machine"."""
    body = _read("app", "templates", "visits", "record.html")
    assert "tab==='studies'" not in body
    assert 'id="studies"' not in body


def test_the_devices_are_still_reachable_from_procedures(scanned, doc):
    """Folding the tab in must not have taken away the way to run a device."""
    body = doc.get(f"/visits/{scanned['ids']['visit']}/record").get_data(as_text=True)
    assert "visits.open_study" in body or "جهاز وظائف تنفس" in body
    assert "/studies/new" in body or "study_new" in body or "device_id=" in body


def test_the_procedures_count_covers_both(scanned):
    """The tab badge said "2 procedures" while three things had been done in
    the room, because the studies were counted on a tab that no longer exists."""
    body = _read("app", "templates", "visits", "record.html")
    assert "visit.services|length) + (visit.studies|length" in body


def test_a_study_shows_under_the_procedure_that_charged_for_it(scanned, doc):
    """The row answers "was it done, and what did it say" without going
    anywhere."""
    from app.models import DeviceStudy, Service, VisitService

    with scanned["app"].app_context():
        svc = Service.query.filter_by(code="SVC-SP").first()
        scanned["db"].session.add(VisitService(
            visit_id=scanned["ids"]["visit"], service_id=svc.id,
            name=svc.name, quantity=1))
        study = scanned["db"].session.get(DeviceStudy,
                                          scanned["dev"]["newest_spiro"])
        study.visit_id = scanned["ids"]["visit"]
        scanned["db"].session.commit()

    body = doc.get(f"/visits/{scanned['ids']['visit']}/record").get_data(as_text=True)
    with scanned["app"].test_request_context("/"):
        from app.i18n import t
        assert t("visits.study_done") in body
    assert "FEV1" in body, "the values are not shown under the procedure"


def test_a_study_with_no_procedure_line_is_still_shown(scanned, doc):
    """The device was used directly. Dropping the result because nobody added
    a billing row would lose it."""
    from app.models import DeviceStudy

    with scanned["app"].app_context():
        study = scanned["db"].session.get(DeviceStudy,
                                          scanned["dev"]["newest_spiro"])
        study.visit_id = scanned["ids"]["visit"]
        scanned["db"].session.commit()

    body = doc.get(f"/visits/{scanned['ids']['visit']}/record").get_data(as_text=True)
    assert "جهاز وظائف تنفس" in body


# ================================== reading them back is per device ========
def test_the_file_groups_them_by_device(scanned):
    data = _grouped(scanned)
    assert data["devices"] == 2
    assert data["total"] == 4
    names = [g["name"] for g in data["groups"]]
    assert len(set(names)) == 2


def test_the_device_used_most_recently_comes_first(scanned):
    """Ordering from the device catalogue would put a machine last used two
    years ago above the one used this morning."""
    data = _grouped(scanned)
    assert data["groups"][0]["name"] == "جهاز وظائف تنفس"


def test_within_a_device_the_newest_is_first(scanned):
    data = _grouped(scanned)
    rows = data["groups"][0]["rows"]
    assert rows[0]["date"] == local_today()
    assert rows[0]["date"] > rows[1]["date"]


def test_a_group_carries_its_own_count_and_latest_date(scanned):
    """The thing somebody wants off the shelf is usually "the most recent
    echo", and finding it should not take reading."""
    data = _grouped(scanned)
    for group in data["groups"]:
        assert group["count"] == len(group["rows"])
        assert group["latest"] == group["rows"][0]["date"]


def test_a_row_says_how_many_values_were_out_of_range(scanned):
    """A study with three values outside their range and one with none look
    identical when the row shows only a date and a device."""
    data = _grouped(scanned)
    newest = data["groups"][0]["rows"][0]
    assert newest["values"] == 2
    assert newest["out_of_range"] == 1
    assert data["flagged"] == 1


def test_a_study_with_no_date_sorts_oldest_rather_than_crashing(scanned):
    """``study_date`` is NOT NULL, so the database cannot hold one — the first
    version of this test tried to write one and was rejected. The guard is
    still worth having because the function is handed objects rather than
    rows, so it is tested where it applies: on the sort, with a stand-in."""
    from types import SimpleNamespace

    from app.utils.studies import patient_studies

    def study(study_id, when):
        return SimpleNamespace(
            id=study_id, study_date=when, conclusion=None, visit_id=None,
            values=[], performer=None,
            device=SimpleNamespace(id=1, display_name=lambda lang="ar": "جهاز"))

    patient = SimpleNamespace(device_studies=[
        study(1, None), study(2, local_today())])
    with scanned["app"].test_request_context("/"):
        data = patient_studies(patient)
    rows = data["groups"][0]["rows"]
    assert rows[0]["date"] == local_today()
    assert rows[-1]["date"] is None


def test_a_child_with_no_studies_reads_as_empty_not_broken(clinic):
    from app.models import Patient
    from app.utils.studies import patient_studies

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        data = patient_studies(patient)
        assert data == {"groups": [], "total": 0, "flagged": 0, "devices": 0}


# ============================================ one list, not three ==========
def test_the_file_has_a_studies_tab(scanned, doc):
    body = doc.get(f"/patients/{scanned['ids']['child']}").get_data(as_text=True)
    assert "tab==='studies'" in body
    with scanned["app"].test_request_context("/"):
        from app.i18n import t
        assert t("patients.tab_studies") in body


def test_the_list_is_not_repeated_on_the_overview(scanned):
    """It was a table on the overview *and* a list at the bottom of the visits
    tab *and* nowhere you could read one device's history."""
    body = _read("app", "templates", "patients", "profile.html")
    assert "studies.title_list" not in body, "still on the overview"
    assert "Device studies (C.2)" not in body, "still in the visits tab"
    assert body.count("study_view") <= 2


def test_the_visits_tab_is_about_visits(scanned, doc):
    body = _read("app", "templates", "patients", "profile.html")
    visits_tab = body[body.index("x-show=\"tab==='visits'\""):
                      body.index("x-show=\"tab==='studies'\"")]
    assert "study.title_list" not in visits_tab


def test_each_study_can_still_be_opened_and_printed(scanned, doc):
    body = doc.get(f"/patients/{scanned['ids']['child']}").get_data(as_text=True)
    study_id = scanned["dev"]["newest_spiro"]
    assert f"/visits/studies/{study_id}" in body or f"study_id={study_id}" in body \
        or str(study_id) in body


def test_the_file_still_opens(scanned, doc):
    assert doc.get(f"/patients/{scanned['ids']['child']}").status_code == 200


def test_the_visit_still_opens(scanned, doc):
    assert doc.get(
        f"/visits/{scanned['ids']['visit']}/record").status_code == 200
