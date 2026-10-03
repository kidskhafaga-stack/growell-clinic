"""The films and the studies: one place of their own, out of the lab.

Asked as *«الاشعة ازاي داخله فى المعمل لازم يبقى ليها تاب لوحده يا ممكن
ندخلها فى "الفحوصات التشخيصية" … يبقى مكان واحد»*, and, with a photo of the
tests list, *«شايف اشعة الايكو … انها تحليل؟»*.

The two worklists already existed; the only way to them was a link on the
lab's own page. And the tests list showed blood counts, films and echoes in
one column, each with a sample box and a unit box. What is held here:

* the menu has a door to the studies, riding the lab module (no new module
  that would start switched off);
* behind it, one screen with a tab per room, each tab carrying its count;
* the tests list has a tab per kind, counted after the search;
* a film or a study has no sample box and no unit box — and saving its row
  does not read their absence as «cleared».
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def catalogue(clinic):
    from app.models import Investigation, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        rows = {
            "cbc": Investigation(name_ar="صورة دم كاملة", kind="lab", unit="g/dL",
                                 sample_type="دم", is_active=True),
            "xray": Investigation(name_ar="أشعة صدر", kind="imaging", is_active=True),
            # An old row typed before the split, with a unit somebody filled in.
            "echo": Investigation(name_ar="إيكو قلب", kind="diagnostic",
                                  unit="old", sample_type="old", is_active=True),
        }
        db.session.add_all(rows.values())
        db.session.commit()
        clinic["ids"].update({k: v.id for k, v in rows.items()})
    return clinic


def test_radiology_is_its_own_module_with_its_own_door(catalogue):
    """«المعمل مديول لواحده والاشعة مديول». It follows the lab until somebody
    sets it, so a copy that had the films under the lab still has them."""
    page = catalogue["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert re.search(r'href="/imaging/"', page)
    films = catalogue["sign_in"]("boss").get("/imaging/").get_data(as_text=True)
    assert re.search(r'class="nav-item gc-press active"\s+href="/imaging/"', films)
    assert not re.search(r'class="nav-item gc-press active"\s+href="/labs/"', films)


def test_radiology_switched_off_on_its_own_leaves_the_lab(catalogue):
    from app.models import Setting

    with catalogue["app"].app_context():
        Setting.set("mod_enabled:imaging", "0")
        catalogue["db"].session.commit()
    client = catalogue["sign_in"]("boss")
    assert client.get("/imaging/").status_code in (302, 403, 404)
    lab = client.get("/labs/").get_data(as_text=True)
    assert lab and 'href="/imaging/"' not in lab


def test_the_split_runs_once_and_keeps_every_role_that_had_the_lab(catalogue):
    from app.models import Setting
    from app.models.role import Role
    from app.utils.schema import split_imaging_from_labs

    with catalogue["app"].app_context():
        db = catalogue["db"]
        db.session.add(Role(name="tech", modules="dashboard,labs,patients"))
        db.session.add(Role(name="front", modules="dashboard,patients"))
        db.session.commit()
        assert split_imaging_from_labs() is True
        db.session.commit()
        assert Setting.get("mod_enabled:imaging") == "1"
        assert Role.query.filter_by(name="tech").one().modules == "dashboard,labs,imaging,patients"
        assert Role.query.filter_by(name="front").one().modules == "dashboard,patients"
        # A clinic that later switches radiology off is not overruled.
        Setting.set("mod_enabled:imaging", "0")
        assert split_imaging_from_labs() is False
        assert Setting.get("mod_enabled:imaging") == "0"


def test_a_licence_that_names_the_lab_covers_radiology(catalogue, monkeypatch):
    from app.utils import licensing

    monkeypatch.setattr(licensing, "licensed_modules", lambda: {"labs", "visits"})
    assert licensing.module_licensed("imaging") is True
    monkeypatch.setattr(licensing, "licensed_modules", lambda: {"visits"})
    assert licensing.module_licensed("imaging") is False


def test_the_tests_list_has_a_tab_per_kind(catalogue):
    client = catalogue["sign_in"]("boss")
    lab = client.get("/labs/tests").get_data(as_text=True)
    assert "صورة دم كاملة" in lab and "أشعة صدر" not in lab and "إيكو قلب" not in lab
    studies = client.get("/labs/tests?kind=diagnostic").get_data(as_text=True)
    assert "إيكو قلب" in studies and "صورة دم كاملة" not in studies
    # The search counts across every tab, so a match elsewhere is said.
    found = client.get("/labs/tests?q=إيكو").get_data(as_text=True)
    tab = found.split('data-kind-tab="diagnostic"', 1)[1][:400]
    assert '<span class="badge badge--muted">1</span>' in tab


def test_a_study_has_no_sample_box_and_saving_it_keeps_what_was_there(catalogue):
    from app.models import Investigation

    client = catalogue["sign_in"]("boss")
    page = client.get("/labs/tests?kind=diagnostic").get_data(as_text=True)
    form = page.split(f'data-test="{catalogue["ids"]["echo"]}"', 1)[1].split("</form>", 1)[0]
    assert 'name="unit"' not in form and 'name="sample_type"' not in form
    # A device study shows its device and booking instead (device board).
    assert "data-device-pick" in form and "data-needs-booking-box" in form
    client.post(f"/labs/tests/{catalogue['ids']['echo']}",
                data={"name_ar": "إيكو على القلب", "is_active": "1", "in_house": "1"})
    with catalogue["app"].app_context():
        row = catalogue["db"].session.get(Investigation, catalogue["ids"]["echo"])
        assert row.name_ar == "إيكو على القلب"
        assert row.unit == "old" and row.sample_type == "old"


def test_a_lab_test_still_saves_its_unit_and_sample(catalogue):
    from app.models import Investigation

    client = catalogue["sign_in"]("boss")
    client.post(f"/labs/tests/{catalogue['ids']['cbc']}",
                data={"name_ar": "صورة دم كاملة", "unit": "", "sample_type": "دم",
                      "is_active": "1", "in_house": "1"})
    with catalogue["app"].app_context():
        row = catalogue["db"].session.get(Investigation, catalogue["ids"]["cbc"])
        assert row.unit is None and row.sample_type == "دم"


def test_adding_a_scan_keeps_no_sample_and_lands_on_its_tab(catalogue):
    from app.models import Investigation

    answer = catalogue["sign_in"]("boss").post(
        "/labs/tests/add", data={"name_ar": "بانوراما أسنان", "kind": "imaging",
                                 "unit": "x", "sample_type": "y", "in_house": "1"})
    assert "kind=imaging" in answer.headers["Location"]
    with catalogue["app"].app_context():
        row = Investigation.query.filter_by(name_ar="بانوراما أسنان").one()
        assert row.kind == "imaging" and row.unit is None and row.sample_type is None


def test_no_badge_is_handed_to_the_number_animation_without_a_number():
    """**Both racks' badges read a bare «0».** `app.js` rewrites every
    `[data-count]` to the number in the attribute, and the lab's and the
    studies' badges carried a *name* there (`to_collect`, `to_do`) — so «3 to
    draw» became «0» a second after the page loaded, whatever was waiting.
    Every `data-count` in a template must hold a number or an expression."""
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    bad = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            text = open(os.path.join(base, name), encoding="utf-8").read()
            for value in re.findall(r'data-count="([^"]*)"', text):
                if not (value.startswith("{{") or re.fullmatch(r"-?\d+(\.\d+)?", value)):
                    bad.append(f"{name}: {value}")
    assert not bad, bad


# ------------------------------------------- the ECG done at the trolley --
def _er_with_study(clinic, kind="diagnostic", name="رسم قلب"):
    from datetime import datetime, timedelta

    from app.models import Patient, Setting, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:emergency", "1")
        child = db.session.get(Patient, clinic["ids"]["child"])
        row = util.arrive(child, at=datetime.utcnow() - timedelta(minutes=10))
        db.session.flush()
        test = eo.order_test(row, db.session.get(User, clinic["ids"]["doctor"]),
                             name=name, kind=kind)
        db.session.commit()
        return row.id, test.id


def test_an_ecg_in_emergency_is_marked_done_where_it_was_done(catalogue):
    from app.models import VisitInvestigation

    attendance, test = _er_with_study(catalogue)
    client = catalogue["sign_in"]("doc")
    page = client.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert f'data-er-test-done="{test}"' in page
    answer = client.post(f"/emergency/attendance/{attendance}/test/{test}/done")
    assert answer.headers["Location"].endswith(f"/emergency/attendance/{attendance}#tests")
    with catalogue["app"].app_context():
        row = catalogue["db"].session.get(VisitInvestigation, test)
        assert row.performed_at is not None and row.collected_at is None
        assert row.sample_code is None and row.status == "collected"
    page = client.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert f'data-er-test-done="{test}"' not in page
    assert f"/labs/order/{test}" in page, "nowhere to write the report"


def test_a_blood_test_has_no_done_now_and_cannot_be_forced(catalogue):
    from app.models import VisitInvestigation

    attendance, test = _er_with_study(catalogue, kind="lab", name="صورة دم")
    client = catalogue["sign_in"]("doc")
    page = client.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert f'data-er-test-done="{test}"' not in page
    client.post(f"/emergency/attendance/{attendance}/test/{test}/done")
    with catalogue["app"].app_context():
        row = catalogue["db"].session.get(VisitInvestigation, test)
        assert row.performed_at is None and row.status == "requested"


def test_another_childs_order_is_not_reached_through_this_page(catalogue):
    from app.models import VisitInvestigation

    attendance, _ = _er_with_study(catalogue)
    with catalogue["app"].app_context():
        db = catalogue["db"]
        other = VisitInvestigation(visit_id=catalogue["ids"]["visit"], patient_id=catalogue["ids"]["child"],
                                   kind="diagnostic", name="إيكو", status="requested")
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    answer = catalogue["sign_in"]("doc").post(
        f"/emergency/attendance/{attendance}/test/{other_id}/done")
    assert answer.status_code == 404
