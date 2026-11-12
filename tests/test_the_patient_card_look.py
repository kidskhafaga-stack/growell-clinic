"""The patient card's look is the clinic's choice (asked: «نعمل إعدادات لشكل
كارت المريض زي ما بعتها … الأساسي ولا الاقتراحات ولا العيادة تحط شعارها …
الاختصارات ولا يبين كله»).

Design, the mark (whose, colour, how strong, where), the shortcuts and the
picture's shape — saved in Settings → logo, read on every card. The defaults
are the card as it was, so an update changes nothing.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _card(clinic, who="doc"):
    page = clinic["sign_in"](who).get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    start = page.index("data-file-header")
    return page[start:page.index("data-file-actions", start)]


def test_the_defaults_are_the_card_as_it_was(clinic):
    card = _card(clinic)
    for attr in ('data-card-style="waves"', 'data-card-src="program"', 'data-card-color="brand"',
                 'data-card-pos="corner"', 'data-card-keys="menu"', "--mark-op:0.12",
                 "img/brand/pediapro-mark.png"):
        assert attr in card, attr


def test_the_choice_is_saved_and_read_on_every_card(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    page = boss.get("/settings/").get_data(as_text=True)
    assert "data-card-look-setting" in page and "data-card-preview" in page
    boss.post("/settings/", data={"card_style": "accent", "card_logo": "program", "card_color": "mono",
                                  "card_opacity": "20", "card_pos": "center", "card_keys": "all",
                                  "active_tab": "logo"})
    with clinic["app"].app_context():
        assert Setting.get("card_style") == "accent" and Setting.get("card_keys") == "all"
    card = _card(clinic)
    for attr in ('data-card-style="accent"', 'data-card-color="mono"', 'data-card-pos="center"',
                 'data-card-keys="all"', "--mark-op:0.20"):
        assert attr in card, attr


def test_nonsense_falls_back_and_the_strength_stays_in_range(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("card_style", "neon")
        Setting.set("card_opacity", "90")
        clinic["db"].session.commit()
    card = _card(clinic)
    assert 'data-card-style="waves"' in card and "--mark-op:0.25" in card


def test_the_clinic_logo_until_there_is_one_is_the_program_s(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("card_logo", "clinic")
        clinic["db"].session.commit()
    card = _card(clinic)
    assert 'data-card-logo="clinic"' in card and 'data-card-src="program"' in card
    assert "img/brand/pediapro-mark.png" in card
    with clinic["app"].app_context():
        Setting.set("clinic_logo", "our-logo.png")
        clinic["db"].session.commit()
    card = _card(clinic)
    assert 'data-card-src="clinic"' in card and "uploads/clinic/our-logo.png" in card


def test_the_look_reaches_every_screen_with_a_child_on_top():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for name in ("patients/profile.html", "visits/record.html", "emergency/attendance.html",
                 "beds/admission.html", "vaccinations/view.html", "growth/chart.html"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "{{ card_attrs() }}" in text and "{{ card_mark() }}" in text, name


def test_every_look_keeps_the_safety_and_the_menu_opens_itself():
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "css", "theme.css"),
               encoding="utf-8").read()
    look = css[css.index("/* ---- The card's look"):css.index("/* The card's settings")]
    assert "vs-red" not in look and "vs-amber" not in look, "no look restyles the allergy or the chronic box"
    js = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "app.js"),
              encoding="utf-8").read()
    assert '.ph2[data-card-keys="all"] details.ph2-more' in js
