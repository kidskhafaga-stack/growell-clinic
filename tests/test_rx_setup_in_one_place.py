"""Setting a doctor up to print a prescription, without borrowing their login.

Everything a printed prescription needs was already in the database and every
piece of it was already editable. It was editable in three places, and one of
those places was the doctor's own profile screen.

So the person who sets a clinic up could type a doctor's name, title, licence
and qualification lines on the admin's doctor screen, upload a stamp on the
general user form, and then have no way at all to say *which layout* to print
them on — that picker existed only at ``/profile``, which shows whoever is
logged in. The honest description of the old workflow is: ask the doctor for
their password, or ask the doctor to do it and hope they do.

The layouts themselves stay one list for the whole clinic. A layout is a
description of a piece of paper, and a clinic buys one kind of paper; what is
per-doctor is which of them this doctor's prescriptions come out on, and that
is now on the screen where the rest of that doctor's setup already lives.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _templates(clinic):
    """Two layouts to choose between, the way a real clinic has them."""
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        preprinted = RxPrintTemplate(name="ورق العيادة", mode="preprinted",
                                     page_size="A5", is_default=True)
        white = RxPrintTemplate(name="ورق أبيض", mode="white", page_size="A4")
        db.session.add_all([preprinted, white])
        db.session.commit()
        return {"preprinted": preprinted.id, "white": white.id}


def test_an_admin_can_choose_a_doctors_layout_without_their_password(clinic):
    """The gap this closes, stated as the thing that used to be impossible."""
    ids = _templates(clinic)
    doctor = clinic["ids"]["doctor"]
    client = clinic["sign_in"]("boss")

    page = client.get(f"/users/doctors/{doctor}")
    assert page.status_code == 200
    assert 'name="rx_template_id"' in page.get_data(as_text=True)

    client.post(f"/users/doctors/{doctor}/rx",
                data={"rx_template_id": ids["white"]}, follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import User
        assert clinic["db"].session.get(User, doctor).rx_template_id == ids["white"]


def test_the_printed_prescription_actually_follows_the_choice(clinic):
    """Storing the id would be worthless if printing ignored it.

    The picker and the printer are separate code, so this asserts the whole
    path: what an admin chose on the doctor's screen is what the prescription
    resolver hands back for that doctor.
    """
    ids = _templates(clinic)
    doctor = clinic["ids"]["doctor"]
    client = clinic["sign_in"]("boss")
    client.post(f"/users/doctors/{doctor}/rx",
                data={"rx_template_id": ids["white"]}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.blueprints.prescriptions.routes import resolve_template
        from app.models import User
        doc = clinic["db"].session.get(User, doctor)
        chosen = resolve_template(doc)
        # Not the clinic default (the pre-printed one), because this doctor
        # was given their own.
        assert chosen.mode == "white"
        assert chosen.page_size == "A4"


def test_clearing_the_choice_falls_back_to_the_clinic_default(clinic):
    """"None" has to mean the clinic's paper, not "print nothing"."""
    ids = _templates(clinic)
    doctor = clinic["ids"]["doctor"]
    client = clinic["sign_in"]("boss")
    client.post(f"/users/doctors/{doctor}/rx",
                data={"rx_template_id": ids["white"]}, follow_redirects=True)
    client.post(f"/users/doctors/{doctor}/rx", data={"rx_template_id": ""},
                follow_redirects=True)

    with clinic["app"].app_context():
        from app.blueprints.prescriptions.routes import resolve_template
        from app.models import User
        doc = clinic["db"].session.get(User, doctor)
        assert doc.rx_template_id is None
        assert resolve_template(doc).mode == "preprinted"


def test_a_layout_deleted_since_the_form_loaded_is_not_stored(clinic):
    """Two admins, one of them tidying up.

    A stale dropdown posts an id that no longer exists. Writing it would leave
    the doctor pointing at nothing, and the resolver would fall through to the
    clinic default anyway — but silently, with the doctor's screen still
    showing a selection that is not real. Better to store no choice, which the
    screen then shows honestly as "the clinic's default".
    """
    ids = _templates(clinic)
    doctor = clinic["ids"]["doctor"]
    client = clinic["sign_in"]("boss")
    client.post(f"/users/doctors/{doctor}/rx",
                data={"rx_template_id": ids["white"]}, follow_redirects=True)
    client.post(f"/users/doctors/{doctor}/rx",
                data={"rx_template_id": 999999}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import User
        assert clinic["db"].session.get(User, doctor).rx_template_id is None


def test_only_an_admin_can_set_another_doctors_paper(clinic):
    """Convenience for the admin is not permission for everybody.

    Bringing the setting onto a shared screen must not turn "which layout do I
    print on" into something a receptionist can change for a doctor.
    """
    ids = _templates(clinic)
    doctor = clinic["ids"]["doctor"]
    desk = clinic["sign_in"]("desk")
    page = desk.post(f"/users/doctors/{doctor}/rx",
                     data={"rx_template_id": ids["white"]},
                     follow_redirects=False)
    assert page.status_code in (302, 403)
    with clinic["app"].app_context():
        from app.models import User
        assert clinic["db"].session.get(User, doctor).rx_template_id is None


def test_the_layouts_screen_is_reachable_from_settings(clinic):
    """It used to be reachable only from a prescription that already existed.

    Which means the first prescription of a clinic's life was printed on
    whatever the defaults happened to be, because the screen that would have
    changed them could only be opened from the page you get *after* printing.
    """
    page = clinic["sign_in"]("boss").get("/settings/", follow_redirects=True)
    assert "/prescriptions/templates" in page.get_data(as_text=True)


def test_the_doctors_screen_does_not_call_it_mine(clinic):
    """Whose paper it is matters on a screen about somebody else.

    The picker on ``/profile`` is labelled "my prescription template" and is
    correct there. Reusing that string here would have an admin reading "my"
    about a layout that is not theirs and a doctor who is not them.
    """
    _templates(clinic)
    body = (clinic["sign_in"]("boss")
            .get(f"/users/doctors/{clinic['ids']['doctor']}")
            .get_data(as_text=True))
    assert "قالب الروشتة الخاص بي" not in body
    assert "شكل الروشتة" in body
