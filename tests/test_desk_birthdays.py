"""Today, tomorrow, and the rest of the week — told apart at a glance.

The birthdays moved to the desk when the module stopped opening in its own
settings, and the move flattened them: the old card had the child's age, a
green pill for today and a muted one for the rest, and the desk version was a
plain table of names with the day in ordinary text. Reported as: the screen
that had the birthdays had a nice animation, it lit up and faded, and it
distinguished today's people from tomorrow's.

**The distinction is carried by shape before colour.** A filled medallion for
today, a dashed ring for tomorrow, a plain ring holding the number of days
for the rest. Colour alone reads fine for most people and not at all for
anybody who cannot separate the greens, and the card exists to be read on the
way past rather than studied — so the shape is the test, not the tint.

The dark-mode assertion here is not about this card. `.badge--green` and
`.badge--role` took their background from tokens the dark palette redefines
and their text from tokens it does not, so they rendered dark-on-dark
everywhere — 195 uses across 78 templates. It surfaced here because this is
where two of them sit side by side.
"""
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
THEME = os.path.join(ROOT, "app/static/css/theme.css")


def _birthday(clinic, name, in_days, phone="01000000000", number=None):
    """A child whose birthday falls `in_days` days from the clinic's today."""
    from app.extensions import db
    from app.models import Patient

    when = local_today() + timedelta(days=in_days)
    kid = Patient(patient_number=number or f"BD{in_days}{name[:2]}",
                  full_name=name, gender="female",
                  date_of_birth=date(2020, when.month, when.day),
                  own_phone=phone, is_active=True)
    db.session.add(kid)
    db.session.flush()
    return kid


def _desk(clinic, build=None):
    from app.extensions import db

    if build is not None:
        with clinic["app"].app_context():
            build()
            db.session.commit()
    return clinic["sign_in"]("desk").get("/messages/desk").data.decode()


def _rows(page):
    """The birthday rows, in the order the page lists them."""
    return re.findall(r'class="bday-row bday-row--(\w+)"', page)


# ----------------------------------------------------------- the three shapes

def test_todays_child_gets_the_filled_medallion(clinic):
    page = _desk(clinic, lambda: _birthday(clinic, "مريم", 0))

    assert "bday-medal--today" in page, "today is not marked out at all"
    assert "bday-row--today" in page


def test_tomorrow_is_its_own_shape_not_just_another_row(clinic):
    """The thing that was actually asked for: today's people and tomorrow's."""
    page = _desk(clinic, lambda: _birthday(clinic, "آدم", 1))

    assert "bday-medal--tomorrow" in page, \
        "tomorrow looks the same as next Thursday"
    assert "bday-medal--today" not in page


def test_the_rest_of_the_week_carries_its_number(clinic):
    page = _desk(clinic, lambda: _birthday(clinic, "ليلى", 4))

    assert "bday-medal--later" in page
    assert re.search(r'class="bday-days">\s*4\s*<', page), \
        "the day count is not on the medallion"


def test_all_three_can_appear_at_once_and_stay_distinct(clinic):
    """The case the card is for — and the one a single tint would blur."""
    def build():
        _birthday(clinic, "النهاردة", 0)
        _birthday(clinic, "بكره", 1)
        _birthday(clinic, "بعدين", 5)

    page = _desk(clinic, build)

    assert _rows(page) == ["today", "tomorrow", "later"], \
        f"the three days are not distinct or not in order: {_rows(page)}"


def test_the_shape_is_not_carried_by_colour_alone(clinic):
    """A reader who cannot separate the greens still has to be able to tell.

    Asserted on the CSS rather than the markup: the classes could all be
    present and every one of them painted the same.
    """
    with open(THEME, encoding="utf-8") as fh:
        css = fh.read()

    today = css[css.index(".bday-medal--today"):][:400]
    tomorrow = css[css.index(".bday-medal--tomorrow"):][:300]
    later = css[css.index(".bday-medal--later"):][:300]

    assert "background: var(--green-600)" in today, "today is not filled"
    assert "dashed" in tomorrow, "tomorrow is not a dashed ring"
    assert "dashed" not in later and "solid" in later, \
        "tomorrow and the rest of the week are the same shape"


# ----------------------------------------------------------- what it lit up

def test_today_lights_up_and_stops(clinic):
    """"تنور وطفى" — and then stops.

    An animation that never stops, on a screen somebody sits in front of all
    day, turns from a nice touch into the reason they ask for it removed. So
    the iteration count is asserted as finite, not just present.
    """
    with open(THEME, encoding="utf-8") as fh:
        css = fh.read()

    block = css[css.index(".bday-medal--today"):][:400]
    found = re.search(r"animation:\s*bday-glow\s+[\d.]+s\s+[\w-]+\s+(\S+);", block)

    assert found, f"today's medallion has no glow: {block[:160]}"
    assert found.group(1) != "infinite", \
        "the glow never stops, which is how a nice animation becomes a complaint"
    assert int(found.group(1)) >= 1


def test_the_glow_follows_the_clinics_own_accent(clinic):
    """The shared `gc-pulse-ring` hardcodes a green.

    `--green-600` is redefined to the clinic's accent, so a clinic with a blue
    accent got a green ring pulsing around a blue disc. Measured in Chromium
    on a clinic whose accent is blue.
    """
    with open(THEME, encoding="utf-8") as fh:
        css = fh.read()

    assert "@keyframes bday-glow" in css
    glow = css[css.index("@keyframes bday-glow"):][:400]
    assert "var(--green-600)" in glow, \
        "the glow paints a fixed colour instead of the clinic's accent"


def test_the_rows_come_in_staggered_rather_than_all_at_once(clinic):
    page = _desk(clinic, lambda: _birthday(clinic, "مريم", 0))

    assert "bday-list gc-stagger" in page, "the list appears in one block"


# ------------------------------------------------------ what it says per row

def test_the_age_is_back(clinic):
    """It was on the old card and it is what makes the greeting personal."""
    from app.i18n import t

    page = _desk(clinic, lambda: _birthday(clinic, "مريم", 0))

    with clinic["app"].test_request_context("/"):
        expected = t("messages_mod.desk_turning", n=6)
    assert expected in page, "the child's age is not on the row"


def test_a_child_with_no_number_is_told_rather_than_given_a_dead_button(clinic):
    from app.i18n import t

    page = _desk(clinic, lambda: _birthday(clinic, "بلا رقم", 0, phone=None))

    with clinic["app"].test_request_context("/"):
        assert t("messages_mod.desk_no_phone") in page, \
            "a child with no number still gets a send button that can only fail"


def test_a_child_with_a_number_still_gets_the_send_button(clinic):
    page = _desk(clinic, lambda: _birthday(clinic, "مريم", 0))

    assert "/messages/occasions/birthday/" in page, \
        "the send button went missing with the redesign"


def test_an_empty_week_still_says_so(clinic):
    from app.i18n import t

    page = _desk(clinic)

    with clinic["app"].test_request_context("/"):
        assert t("messages_mod.desk_birthdays_none")[:15] in page


# ---------------------------------------------- the dark-mode legibility bug

def test_the_green_badges_are_readable_in_the_dark(clinic):
    """Pre-existing and app-wide, found because two of them sit together here.

    The dark palette redefines `--green-100`/`--green-050`, which are these
    badges' *backgrounds*, and leaves `--green-900`/`--green-800`, which are
    their *text*. Dark on dark. `.badge--muted` and `.badge--danger` beside
    them already had dark variants; these two were missed.
    """
    with open(THEME, encoding="utf-8") as fh:
        css = fh.read()

    for badge in (".badge--green", ".badge--role"):
        rule = f':root[data-theme="dark"] {badge}'
        assert rule in css, (
            f"{badge} has no dark variant, so it renders its dark text on the "
            "dark background the palette gives it")


def test_the_dark_variants_are_not_just_the_light_ones_again(clinic):
    """A variant that repeats the broken pair would pass the test above."""
    with open(THEME, encoding="utf-8") as fh:
        css = fh.read()

    block = css[css.index(':root[data-theme="dark"] .badge--green'):][:300]
    assert "--green-900" not in block and "--green-800" not in block, \
        "the dark variant reuses the light-mode text token that caused this"
