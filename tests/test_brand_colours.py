"""The program looks like its own logo.

It has shipped as **PediaPro** all along — the name is in the footer of every
screen and on the mark in the sidebar — and the logo is blue with a green
leaf. The interface was green from top to bottom, so the product did not
resemble its own brand anywhere.

Nothing was rebuilt for this. The clinic accent has driven the whole palette
since it was written: one colour recolours the sidebar, the buttons, the chips
and the cards. All that changed is what a clinic gets **before** it chooses
anything, which used to be the old green typed into two files.

The tests below are mostly about the second half of that sentence — a clinic
that picks its own colour must keep it, or this is not a default, it is a
rule.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_a_clinic_that_chose_nothing_gets_the_brand(clinic):
    from app.utils.brand import PRIMARY

    page = clinic["sign_in"]("boss").get("/patients/").data.decode()
    assert f"--accent:{PRIMARY}" in page


def test_a_clinic_that_chose_a_colour_keeps_it(clinic):
    """The accent is the clinic's, not the product's. A default that
    overrides a choice is not a default."""
    from app.models import Setting

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_accent", "#8E44AD")
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/patients/").data.decode()
    assert "--accent:#8E44AD" in page


def test_a_user_who_chose_a_colour_beats_both(clinic):
    """The order was already there and is worth keeping: mine, then the
    clinic's, then the brand's."""
    from app.models import Setting, User

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_accent", "#8E44AD")
        db.session.get(User, clinic["ids"]["admin"]).accent_color = "#C0392B"
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/patients/").data.decode()
    assert "--accent:#C0392B" in page


def test_the_colours_live_in_one_place(clinic):
    """"The brand blue" typed into a stylesheet and again into a template is
    how a rebrand half-happens."""
    from app.utils import brand

    assert brand.PRIMARY.startswith("#") and len(brand.PRIMARY) == 7
    assert brand.SECONDARY.startswith("#") and len(brand.SECONDARY) == 7

    root = os.path.join(os.path.dirname(__file__), "..", "app")
    stray = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith((".html", ".css")):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                if brand.PRIMARY.lower() in fh.read().lower():
                    stray.append(os.path.relpath(path, root))
    assert not stray, ("the brand colour is written out by hand in: "
                       + ", ".join(stray))


def test_the_settings_picker_starts_on_what_is_actually_showing(clinic):
    """It offered the old green whatever the screen was painted with, so
    opening settings and saving silently changed the colour."""
    from app.utils.brand import PRIMARY

    page = clinic["sign_in"]("boss").get("/settings/").data.decode()
    assert "#198754" not in page.split('name="clinic_accent"')[1][:200]
    assert PRIMARY in page
