"""Every clinical number a clinic can change has a declared owner.

This test exists because of a wrong claim, made one commit before it. A guard
was written proving the heart and respiratory rate bands live in one module,
and the commit message said *"the numbers are written down in exactly one
place"*. That was true of those two and false of the rest: the fever
thresholds live in `red_flags`, and the oxygen limits lived there as constants
nothing could change. The test asserted what had just been done rather than
the claim that was made about it.

**So this one is careful about what it proves.** It does not go looking for
"every clinical number in the code" — that is not a thing a test can find,
because the code is full of numbers that are not clinical and no rule tells
them apart. What it proves is narrower and checkable:

* every setting key the clinical rules actually read is in the register
* the register describes each one completely enough to edit it safely
* the two modules that judge readings stay separate, on purpose

The first is not a source scan. `red_flags.bands()` builds its keys with an
f-string, so nothing static can see them. The rules are **run**, with
`Setting.get` watched, and every key they ask for has to be registered.
"""
import pytest

from app.utils import clinical_rules as cr


# ------------------------------------------------- what the rules ask for ---
@pytest.fixture
def watched(clinic, monkeypatch):
    """Every settings key the clinical rules read while being exercised."""
    from app.models import Setting

    asked = []
    real = Setting.get

    @staticmethod
    def spy(key, default=None):
        asked.append(key)
        return real(key, default)

    monkeypatch.setattr(Setting, "get", spy)
    return clinic, asked


def _exercise(kit):
    """Run the rules over a spread wide enough to reach every branch."""
    from datetime import timedelta

    from app.models import Patient
    from app.utils import red_flags
    from app.utils.clock import local_today

    class _V:
        def __init__(self, temp=None, spo2=None):
            self.temperature_c = temp
            self.spo2 = spo2

    with kit["app"].app_context():
        for months in (1, 4, 12, 60, 170):
            child = Patient(patient_number=f"R{months}", full_name="ط",
                            gender="male",
                            date_of_birth=local_today() - timedelta(
                                days=int(months * 30.44)))
            for temp in (None, 36.5, 38.2, 39.8):
                for spo2 in (None, 99, 93, 88):
                    red_flags.assess(child, _V(temp, spo2),
                                     "سخونية واسهال وترجيع")
        red_flags.bands()
        red_flags.spo2_limits()


def test_every_clinical_key_the_rules_read_is_registered(watched):
    """The claim, stated as narrowly as it can be proved.

    Run the rules, watch what they ask the settings for, and require that
    every clinical key among them has an owner in the register."""
    kit, asked = watched
    _exercise(kit)

    known = set(cr.by_key())
    clinical = {key for key in asked if key.startswith("triage_")}
    assert clinical, "the rules read no clinical settings at all — check the spy"

    unowned = sorted(clinical - known)
    assert not unowned, (
        "these clinical thresholds are read at runtime and have no owner in "
        "the register: " + ", ".join(unowned))


def test_the_register_does_not_describe_rules_nobody_reads(watched):
    """The other direction. A register that lists thresholds no code consults
    is a screen offering edits that change nothing — which is worse than no
    screen, because somebody will make one and believe it took effect."""
    kit, asked = watched
    _exercise(kit)

    read = {key for key in asked if key.startswith("triage_")}
    dead = sorted(set(cr.by_key()) - read)
    assert not dead, (
        "the register lists thresholds nothing reads: " + ", ".join(dead))


# --------------------------------------------- complete enough to edit it ---
@pytest.mark.parametrize("field", ["parameter", "unit", "default", "owner",
                                   "source", "direction", "context", "action"])
def test_every_rule_is_described_completely(field):
    for rule in cr.registry():
        assert rule.get(field) not in (None, ""), (rule["key"], field)


def test_the_source_is_a_real_sentence_and_not_a_placeholder():
    """A blank or a "TBD" here would make the field furniture on the first
    screen anybody opened, and the provenance already exists — `red_flags`
    states it in its own docstring."""
    for rule in cr.registry():
        assert len(rule["source"]) > 12, rule["key"]


def test_direction_is_declared_and_points_the_right_way():
    """Not a guess a screen can make. A *higher* fever threshold hides
    children; a *lower* oxygen threshold hides them. A register without this
    cannot warn about the edits that matter."""
    for rule in cr.registry():
        assert rule["direction"] in (cr.UP, cr.DOWN), rule["key"]
    assert cr.by_key()["triage_fever_0"]["direction"] == cr.UP
    assert cr.by_key()["triage_spo2_urgent"]["direction"] == cr.DOWN


@pytest.mark.parametrize("key,weaker,stronger", [
    ("triage_fever_0", 39.5, 37.5),
    ("triage_urgent_3", 40.0, 39.0),
    ("triage_spo2_urgent", 88, 94),
    ("triage_spo2_watch", 90, 97),
])
def test_it_can_tell_a_weakening_edit_from_a_tightening_one(key, weaker,
                                                            stronger):
    assert cr.less_sensitive(key, weaker) is True
    assert cr.less_sensitive(key, stronger) is False


def test_an_unreadable_edit_is_not_called_weaker():
    """It is not an edit at all — `value` falls back to the default. Calling
    it weaker would put a warning in front of somebody who typed a typo."""
    assert cr.less_sensitive("triage_fever_0", "abc") is False
    assert cr.less_sensitive("triage_fever_0", None) is False


# ------------------------------------------------- editable, not losable ----
def test_a_clinic_change_is_an_override_and_the_default_survives(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        before = cr.by_key()["triage_fever_1"]["default"]
        Setting.set("triage_fever_1", "39.2")
        clinic["db"].session.commit()

        assert cr.value("triage_fever_1") == 39.2
        assert cr.is_override("triage_fever_1")
        assert cr.by_key()["triage_fever_1"]["default"] == before


def test_clearing_the_override_puts_the_default_back(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("triage_fever_1", "39.2")
        clinic["db"].session.commit()
        Setting.set("triage_fever_1", "")
        clinic["db"].session.commit()

        assert cr.value("triage_fever_1") == \
            cr.by_key()["triage_fever_1"]["default"]
        assert not cr.is_override("triage_fever_1")


def test_an_unreadable_override_falls_back_rather_than_raising(clinic):
    """A threshold that cannot be parsed must not be able to stop a screen
    from rendering, and the default is the safe answer."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("triage_spo2_urgent", "ninety-two")
        clinic["db"].session.commit()
        assert cr.value("triage_spo2_urgent") == \
            cr.by_key()["triage_spo2_urgent"]["default"]


def test_the_override_actually_reaches_the_rule(clinic):
    """The register describing a number is worth nothing if the code that
    decides still reads its own constant. This is the half that was missing
    for the oxygen limits until now."""
    from datetime import timedelta

    from app.models import Patient, Setting
    from app.utils import red_flags
    from app.utils.clock import local_today

    class _V:
        temperature_c = None
        spo2 = 90

    with clinic["app"].app_context():
        child = Patient(patient_number="S1", full_name="ط", gender="male",
                        date_of_birth=local_today() - timedelta(days=400))
        assert red_flags.assess(child, _V(), "")["level"] == "urgent"

        Setting.set("triage_spo2_urgent", "85")
        clinic["db"].session.commit()
        assert red_flags.assess(child, _V(), "")["level"] != "urgent"


# ------------------------------------------ and the two stay separate -------
def test_the_two_judgements_are_still_two(clinic):
    """`vital_bands` says whether a reading is unusual; `red_flags` says
    whether the child needs to be seen now. They disagree about SpO₂ 91 and
    that is not a bug to tidy up — changing a clinical threshold needs a
    source, not a preference for round numbers.

    This holds the difference in place so that nobody merges them by accident
    and nobody 'fixes' the 91 without deciding to."""
    from app.utils import vital_bands
    from app.utils.red_flags import spo2_limits

    with clinic["app"].app_context():
        urgent_below, _watch = spo2_limits()
        assert vital_bands.band("spo2", 12, 91) == vital_bands.BORDERLINE
        assert 91 < urgent_below, (
            "the two modules now agree at 91 — if that was deliberate, this "
            "test should say so and name the source")


# ----------------------------------------------------------- the screen -----
def _screen(clinic):
    return clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)


def test_every_rule_has_a_box_on_the_screen(clinic):
    """The door that was missing. `bands()` has read these from the settings
    since it was written and nothing ever wrote them — the mechanism existed
    and there was no way in."""
    page = _screen(clinic)
    for rule in cr.registry():
        assert f'name="{rule["key"]}"' in page, rule["key"]


def test_the_screen_shows_the_default_and_where_it_came_from(clinic):
    page = _screen(clinic)
    assert "NICE" in page
    assert "38.0" in page and "92" in page


def test_the_screen_shows_no_raw_keys(clinic):
    page = _screen(clinic)
    for key in ("settings.clinical_title", "settings.cr_weaker",
                "settings.cr_p_spo2", "redflags.level_urgent"):
        assert key not in page


def test_saving_a_threshold_stores_it(clinic):
    from app.models import Setting

    clinic["sign_in"]("boss").post(
        "/settings/", data={"triage_fever_1": "38.8"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert Setting.get("triage_fever_1") == "38.8"
        assert cr.value("triage_fever_1") == 38.8


def test_saving_a_blank_restores_the_default(clinic):
    boss = clinic["sign_in"]("boss")
    boss.post("/settings/", data={"triage_fever_1": "38.8"},
              follow_redirects=True)
    boss.post("/settings/", data={"triage_fever_1": ""}, follow_redirects=True)
    with clinic["app"].app_context():
        assert not cr.is_override("triage_fever_1")


def test_a_value_that_is_not_a_number_is_never_stored(clinic):
    """A threshold that cannot be parsed is silently ignored by the rule that
    reads it — which is the worst of both, so it does not get written."""
    boss = clinic["sign_in"]("boss")
    boss.post("/settings/", data={"triage_fever_1": "38.8"},
              follow_redirects=True)
    boss.post("/settings/", data={"triage_fever_1": "high"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert cr.value("triage_fever_1") == 38.8, (
            "a typo replaced a threshold somebody set on purpose")


def test_a_weakening_edit_is_called_out_on_the_screen(clinic):
    """It warns; it never refuses. The clinic decides — but not by
    accident."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("triage_spo2_urgent", "85")
        clinic["db"].session.commit()

    page = _screen(clinic)
    assert "cr_weaker" not in page                    # translated, not raw
    from app.i18n import translate
    with clinic["app"].test_request_context("/"):
        pass
    assert "أقل" in page or "fewer children" in page


def test_a_tightening_edit_is_not_called_out(clinic):
    """A warning on every edit is a warning nobody reads."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("triage_spo2_urgent", "95")
        clinic["db"].session.commit()

    page = _screen(clinic)
    assert "fewer children" not in page and "بتمسك حالات أقل" not in page
