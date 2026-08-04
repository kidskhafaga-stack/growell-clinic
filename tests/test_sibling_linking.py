"""The brother who is already a patient here.

"Add sibling" led to a blank new-patient form and nothing else, which is the
wrong half of the problem. In a clinic that has been open a while the sibling
is **already registered** — his own file number, his own vaccination card, his
own history — from before anybody thought to link the family. Sending somebody
to create him again makes two files for one child, and the empty one is what
the next receptionist finds.

So: link somebody who exists, create a new file when they really do not, and
**suggest**, because the program already holds the two things a receptionist
would go on. Egyptian names carry the father's and grandfather's names, so two
children of one family share their last words far more reliably than they
share a surname field nobody fills in; and a parent's phone is either the same
or it is not, which makes it the strongest signal there is.

Nothing links itself. It proposes with the reason it is proposing — "why is
this person on my screen" is what decides whether anybody trusts the feature —
and merging two children's files is not something to be clever about.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _patient(clinic, name, number, family_id=None):
    from app.models import Patient

    with clinic["app"].app_context():
        row = Patient(patient_number=number, full_name=name, gender="male",
                      date_of_birth=date(2020, 1, 1), family_id=family_id,
                      is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _family(clinic, name="أسرة", phone=None):
    from app.models import Family, Parent

    with clinic["app"].app_context():
        fam = Family(family_name=name)
        clinic["db"].session.add(fam)
        clinic["db"].session.flush()
        if phone:
            clinic["db"].session.add(Parent(family_id=fam.id, full_name="الأب",
                                            relation="father", phone=phone))
        clinic["db"].session.commit()
        return fam.id


def _family_of(clinic, patient_id):
    from app.models import Patient

    with clinic["app"].app_context():
        return clinic["db"].session.get(Patient, patient_id).family_id


# ============================================== linking somebody who exists ==
def test_an_existing_patient_can_be_linked_as_a_sibling(boss, clinic):
    """The action that was missing entirely."""
    fam = _family(clinic)
    a = _patient(clinic, "عمر محمد خفاجة", "P-A", fam)
    b = _patient(clinic, "علي محمد خفاجة", "P-B")

    boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": b},
              follow_redirects=True)
    assert _family_of(clinic, b) == fam


def test_linking_works_even_when_neither_has_a_family_yet(boss, clinic):
    """The commonest case of all — a family row only appears the first time
    somebody records a parent, so two siblings can both be filed under none."""
    a = _patient(clinic, "عمر محمد خفاجة", "P-A")
    b = _patient(clinic, "علي محمد خفاجة", "P-B")

    boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": b},
              follow_redirects=True)
    assert _family_of(clinic, a) is not None
    assert _family_of(clinic, a) == _family_of(clinic, b)


def test_a_child_already_in_another_family_is_refused(boss, clinic):
    """Moving them is a merge, not a link, and a merge is not a one-click
    button on a list of eight suggestions."""
    a = _patient(clinic, "عمر خفاجة", "P-A", _family(clinic, "أ"))
    other = _family(clinic, "ب")
    b = _patient(clinic, "علي خفاجة", "P-B", other)

    body = boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": b},
                     follow_redirects=True).get_data(as_text=True)
    assert _family_of(clinic, b) == other
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("siblings.already_in_family").split("{")[0].strip() in body


def test_linking_a_child_to_themselves_does_nothing(boss, clinic):
    a = _patient(clinic, "عمر", "P-A")
    boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": a},
              follow_redirects=True)
    assert _family_of(clinic, a) is None


def test_a_wrong_link_can_be_undone(boss, clinic):
    """An action with no way back is one people avoid using at all."""
    fam = _family(clinic)
    a = _patient(clinic, "عمر", "P-A", fam)
    b = _patient(clinic, "علي", "P-B")

    boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": b},
              follow_redirects=True)
    boss.post(f"/patients/{a}/siblings/unlink", data={"sibling_id": b},
              follow_redirects=True)
    assert _family_of(clinic, b) is None


def test_linking_is_written_to_the_activity_log(boss, clinic):
    from app.models import ActivityLog

    a = _patient(clinic, "عمر", "P-A")
    b = _patient(clinic, "علي", "P-B")
    boss.post(f"/patients/{a}/siblings/link", data={"sibling_id": b},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="patient.sibling.link").count() == 1


# ========================================================= what it suggests ==
def _hints(clinic, patient_id):
    from app.models import Patient
    from app.utils.siblings import suggest_siblings

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, patient_id)
        return [(h["patient"].patient_number, h["reason"])
                for h in suggest_siblings(patient)]


def test_the_family_part_of_the_name_is_a_suggestion(clinic):
    """Egyptian names carry the father's and grandfather's names, so the last
    words are shared far more reliably than a surname field nobody fills in."""
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic))
    _patient(clinic, "علي محمد الخفاجي", "P-B")
    assert ("P-B", "name") in _hints(clinic, a)


def test_the_spellings_of_the_name_do_not_hide_a_brother(clinic):
    """"الخفاجى" and "الخفاجي" — the same folding the rest of the program
    runs on."""
    a = _patient(clinic, "عمر محمد الخفاجى", "P-A", _family(clinic))
    _patient(clinic, "علي محمد الخفاجي", "P-B")
    assert ("P-B", "name") in _hints(clinic, a)


def test_a_shared_parent_phone_is_a_suggestion(clinic):
    """A number is either the same or it is not, and it is the one thing a
    family gives the clinic every visit.

    This test is why the rule works at all. Written the obvious way — only
    consider patients with no family — the phone branch was dead code, because
    a child registered with a guardian *always* gets a family row, and the
    phone lives on that row. It could never have matched anything.
    """
    a = _patient(clinic, "عمر", "P-A", _family(clinic, "أ", phone="01001234567"))
    _patient(clinic, "شادي", "P-B", _family(clinic, "ب", phone="01001234567"))
    assert ("P-B", "phone") in _hints(clinic, a)


def test_a_different_phone_is_not_a_suggestion(clinic):
    a = _patient(clinic, "عمر", "P-A", _family(clinic, "أ", phone="01001234567"))
    _patient(clinic, "شادي", "P-B", _family(clinic, "ب", phone="01009999999"))
    assert _hints(clinic, a) == []


def test_a_child_in_another_family_is_shown_but_not_linkable(clinic):
    """The commonest shape of the problem, and the honest handling of it:
    finding the brother is most of the value, and joining two households is a
    merge of two sets of parents rather than a link."""
    from app.models import Patient
    from app.utils.siblings import suggest_siblings

    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic, "أ"))
    _patient(clinic, "علي محمد الخفاجي", "P-B", _family(clinic, "ب"))

    with clinic["app"].app_context():
        rows = suggest_siblings(clinic["db"].session.get(Patient, a))
    assert [r["patient"].patient_number for r in rows] == ["P-B"]
    assert rows[0]["in_family"] is True


def test_the_ones_that_can_be_linked_come_first(clinic):
    """A list that opens with three rows needing a merge is a list somebody
    stops reading."""
    from app.models import Patient
    from app.utils.siblings import suggest_siblings

    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic, "أ"))
    _patient(clinic, "أحمد محمد الخفاجي", "P-IN", _family(clinic, "ب"))
    _patient(clinic, "علي محمد الخفاجي", "P-FREE")

    with clinic["app"].app_context():
        rows = suggest_siblings(clinic["db"].session.get(Patient, a))
    assert rows[0]["patient"].patient_number == "P-FREE"


def test_the_phone_is_compared_by_its_tail_not_its_prefix(clinic):
    """+2010… and 0100… are one number, and a family writes it both ways."""
    from app.utils.siblings import _phones

    class _P:
        phone = "+201001234567"
        phone_alt = None

    class _F:
        parents = [_P()]

    assert _phones(_F()) == {"1001234567"}


def test_a_child_who_shares_nothing_is_not_suggested(clinic):
    """A suggestion list that includes everybody is one nobody reads."""
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic))
    _patient(clinic, "يوسف أحمد سالم", "P-B")
    assert _hints(clinic, a) == []


def test_a_child_in_a_family_is_still_surfaced(clinic):
    """Excluding them was the first design and it was wrong: it removed the
    commonest case — two siblings each registered separately — from the very
    list meant to find it."""
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic, "أ"))
    _patient(clinic, "علي محمد الخفاجي", "P-B", _family(clinic, "ب"))
    # Shown, because finding him is the point — but flagged, not linkable.
    assert _hints(clinic, a) == [("P-B", "name")]


def test_a_one_word_name_suggests_nobody(clinic):
    """"محمد" alone is a quarter of Egypt. Two words is the floor."""
    a = _patient(clinic, "محمد", "P-A", _family(clinic))
    _patient(clinic, "محمد", "P-B")
    assert _hints(clinic, a) == []


def test_the_child_themselves_is_never_suggested(clinic):
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic))
    assert all(num != "P-A" for num, _ in _hints(clinic, a))


# ================================================================ the screen ==
def test_the_family_tab_offers_both_actions(boss, clinic):
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic))
    body = boss.get(f"/patients/{a}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("siblings.link_existing") in body
        assert t("patients.add_sibling") in body


def test_the_suggestions_appear_with_their_reason(boss, clinic):
    """"Why is this person on my screen" is what decides whether anybody
    trusts the suggestion or ignores the whole feature."""
    a = _patient(clinic, "عمر محمد الخفاجي", "P-A", _family(clinic))
    _patient(clinic, "علي محمد الخفاجي", "P-B")
    body = boss.get(f"/patients/{a}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("siblings.suggested") in body
        assert t("siblings.why_name") in body


def test_the_search_says_who_cannot_be_linked(boss, clinic):
    """On the row, rather than found out after pressing."""
    a = _patient(clinic, "عمر خفاجة", "P-A", _family(clinic, "أ"))
    _patient(clinic, "علي خفاجة", "P-B", _family(clinic, "ب"))
    rows = boss.get(f"/patients/{a}/siblings/search?q=علي").get_json()["patients"]
    assert rows and rows[0]["in_family"] is True


def test_the_search_needs_something_to_search_for(boss, clinic):
    a = _patient(clinic, "عمر", "P-A")
    assert boss.get(f"/patients/{a}/siblings/search?q=ع").get_json()["patients"] == []


def test_both_languages_carry_the_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("link_existing", "link", "unlink", "suggested",
                    "suggested_hint", "why_phone", "why_name",
                    "already_in_family"):
            assert data["siblings"].get(key), f"{lang}.{key}"
