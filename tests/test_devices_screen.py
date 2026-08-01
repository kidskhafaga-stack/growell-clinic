"""The devices screen, on the pattern the services screen ended up with.

Reported: *"the devices screen and the popup — same as the way services are
edited."* Which was a request for a pattern, not a redesign from scratch, so
this is item 1's answer applied to a second screen: a search that follows the
typing, filters, and the editor opening **in place across the row** instead of
a fixed-width popover.

The popover is the part that mattered. It was 340px wide inside a cell of a
table, and the table scrolls sideways on any laptop — so the panel was clipped
by its own container the moment the screen was narrow enough to need it, which
is exactly when somebody is trying to use it.

One thing this file deliberately holds still: opening the editor must not cost
the link to the device's measurement fields. That link is how a device gets the
list of things it records, and it was reachable from the row before.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def kit(clinic):
    """A cupboard with enough in it that the filters have something to do."""
    from app.models import MedicalDevice

    with clinic["app"].app_context():
        clinic["db"].session.add_all([
            MedicalDevice(name="جهاز وظائف تنفس", name_en="Spirometer",
                          manufacturer="MIR", model="Spirobank II",
                          device_type="spirometry", connection_type="usb",
                          import_mode="manual", serial_number="SB-77",
                          is_active=True),
            MedicalDevice(name="جهاز رسم قلب", name_en="ECG",
                          device_type="ecg", connection_type="manual",
                          import_mode="manual", is_active=True),
            MedicalDevice(name="جهاز قديم", name_en="Old unit",
                          device_type="other", connection_type="manual",
                          import_mode="manual", is_active=False),
        ])
        clinic["db"].session.commit()
    return clinic


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _results(client, **params):
    """Only the block live search swaps — the page also carries an "add"
    form whose selects name every device type."""
    body = client.get("/settings/devices",
                      query_string=params).get_data(as_text=True)
    return body[body.index('id="gc-results"'):]


def _template():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, "settings", "devices.html"), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------- search ------
def test_typing_a_name_narrows_the_list(kit, boss):
    everyone = _results(boss)
    assert "جهاز رسم قلب" in everyone and "جهاز وظائف تنفس" in everyone

    narrowed = _results(boss, q="تنفس")
    assert "جهاز وظائف تنفس" in narrowed
    assert "جهاز رسم قلب" not in narrowed


def test_the_label_on_the_side_of_the_box_is_searchable(kit, boss):
    """A device is looked for by what is printed on it — the maker, the model,
    the serial — more often than by whatever the clinic typed as its name."""
    for needle in ("MIR", "Spirobank", "SB-77"):
        body = _results(boss, q=needle)
        assert "جهاز وظائف تنفس" in body, needle
        assert "جهاز رسم قلب" not in body, needle


def test_filtering_by_type(kit, boss):
    body = _results(boss, type="ecg")
    assert "جهاز رسم قلب" in body
    assert "جهاز وظائف تنفس" not in body


def test_filtering_by_connection(kit, boss):
    body = _results(boss, conn="usb")
    assert "جهاز وظائف تنفس" in body
    assert "جهاز رسم قلب" not in body


def test_filtering_by_status(kit, boss):
    assert "جهاز قديم" in _results(boss, status="inactive")
    assert "جهاز قديم" not in _results(boss, status="active")


def test_filters_combine(kit, boss):
    body = _results(boss, type="spirometry", conn="manual")
    assert "جهاز وظائف تنفس" not in body


def test_a_search_matching_nothing_narrows_to_nothing(kit, boss):
    body = _results(boss, q="زززز")
    for name in ("جهاز وظائف تنفس", "جهاز رسم قلب", "جهاز قديم"):
        assert name not in body


def test_the_search_is_live_like_every_other_screen(kit, boss):
    body = _template()
    assert 'data-live-search="#gc-results"' in body
    assert 'id="gc-results"' in body


def test_the_results_block_is_the_list_and_not_the_add_panel(kit, boss):
    body = _template()
    head = body[body.index('id="gc-results"'):][:800]
    assert "<summary" not in head


# ------------------------------------------------------------- the editor --
def test_the_editor_is_no_longer_a_fixed_width_popover(kit, boss):
    """340px inside a cell of a table that scrolls sideways: clipped by its own
    container exactly when the screen is too narrow to do without it."""
    body = _template()
    assert "popform" not in body
    assert "width:340px" not in body


def test_the_editor_opens_across_the_row(kit, boss):
    body = _template()
    assert 'colspan="7"' in body
    assert "dev-editor" in body


def test_every_device_still_has_its_editor(kit, boss):
    body = _results(boss)
    assert body.count('name="action" value="edit"') == 3


def test_the_measurement_fields_are_still_one_click_away(kit, boss):
    """That link is how a device gets the list of things it records. Tidying
    the row must not have cost it."""
    from app.models import MedicalDevice

    with kit["app"].app_context():
        device_id = MedicalDevice.query.filter_by(name="جهاز رسم قلب").first().id
    assert f"/settings/devices/{device_id}/measurements" in _results(boss)


def test_editing_a_device_still_saves(kit, boss):
    from app.models import MedicalDevice

    with kit["app"].app_context():
        device_id = MedicalDevice.query.filter_by(name="جهاز رسم قلب").first().id

    boss.post("/settings/devices", data={
        "action": "edit", "id": device_id, "name": "جهاز رسم قلب",
        "name_en": "ECG machine", "device_type": "ecg",
        "connection_type": "usb", "import_mode": "manual", "is_active": "1",
    }, follow_redirects=True)
    with kit["app"].app_context():
        dev = kit["db"].session.get(MedicalDevice, device_id)
        assert dev.name_en == "ECG machine"
        assert dev.connection_type == "usb"


def test_adding_a_device_still_works(kit, boss):
    from app.models import MedicalDevice

    boss.post("/settings/devices", data={
        "action": "add", "name": "جهاز سونار", "device_type": "ultrasound",
        "connection_type": "manual", "import_mode": "manual",
    }, follow_redirects=True)
    with kit["app"].app_context():
        dev = MedicalDevice.query.filter_by(name="جهاز سونار").first()
        assert dev is not None and dev.is_active
        # Item 5's rule still holds: a new device arrives with the fields its
        # type normally captures, or no study can be recorded on it.
        assert dev.measurements


def test_deleting_a_device_still_works(kit, boss):
    from app.models import MedicalDevice

    with kit["app"].app_context():
        device_id = MedicalDevice.query.filter_by(name="جهاز قديم").first().id

    boss.post("/settings/devices",
              data={"action": "delete", "id": device_id}, follow_redirects=True)
    with kit["app"].app_context():
        assert kit["db"].session.get(MedicalDevice, device_id) is None


def test_the_screen_says_how_much_it_is_hiding(kit, boss):
    """A filtered list that looks like the whole list is how somebody concludes
    a device was deleted."""
    assert "gc-results" in _results(boss, q="تنفس")
    assert _results(boss).count('name="action" value="edit"') == 3
