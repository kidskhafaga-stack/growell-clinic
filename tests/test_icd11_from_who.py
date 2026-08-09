"""Getting ICD-11 into the program, and not lying about it until it is there.

**The bug this starts from.** The visit screen offered a doctor a choice
between ICD-10 and ICD-11. Nothing of ICD-11 was loaded — not one code — so
choosing it produced an empty search, and an empty search is indistinguishable
from "no such diagnosis exists". The module's own docstring said ICD-11 was
"importable in full"; what existed was :func:`install_full`, the storage half,
with nothing anywhere calling it. So the option was real and the data never
was.

The fix is in two parts and the second is the one that matters: an importer
that actually fetches it, and a picker that asks what is *loaded* rather than
what the program understands. The option and the data now arrive together.

**Why an import rather than a live search.** WHO's API is the only source —
there is no file to ship. But a diagnosis picker that queries WHO on every
keystroke stops working when the line drops, and it does so silently: the
doctor types, nothing appears, and there is no way to tell "no such code" from
"no internet" with a parent sitting there. Imported once, ICD-11 searches at
exactly the speed of the bundled ICD-10 and needs nothing.

**Why the parsing is tested and the transport is barely tested.** This was
written in an environment where WHO is unreachable — the egress proxy answers
403 to `icd.who.int`. Rather than pretend, everything that decides what a code
*is* was made a plain function over payloads WHO has already sent, and those
are tested here against WHO's documented response shape. The transport is kept
thin enough that there is little room for it to hide a bug, and the clinic
finds out about it in one second through the test-connection button instead of
at the end of a twenty-minute walk.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# WHO's real payload shape: human strings wrapped as {"@value": ...}, children
# as absolute URIs, and no `code` at all on chapters and blocks.
ROOT = "https://id.who.int/icd/release/11/mms"
TREE = {
    ROOT: {"@id": "root", "title": {"@value": "ICD-11 MMS"},
           "child": ["u/ch1", "u/ch2"]},
    "u/ch1": {"@id": "ch1",
              "title": {"@value": "Certain infectious &amp; parasitic diseases"},
              "child": ["u/1A00", "u/1A01"]},
    # Reaches 1A00 as well: the classification is a graph, not a tree.
    "u/ch2": {"@id": "ch2", "title": {"@value": "Neoplasms"},
              "child": ["u/2A00", "u/1A00"]},
    "u/1A00": {"@id": "a", "code": "1A00", "title": {"@value": "Cholera"}},
    "u/1A01": {"@id": "b", "code": "1A01", "title": {"@value": "Typhoid fever"}},
    "u/2A00": {"@id": "c", "code": "2A00", "title": {"@value": "Leukaemia"}},
}


class _Resp:
    def __init__(self, payload, ok=True, status=200):
        self._payload, self.ok, self.status_code = payload, ok, status

    def json(self):
        return self._payload


class FakeWho:
    """A WHO that answers, counting what was asked of it."""

    def __init__(self, tree=None, token_ok=True, token_status=200):
        import requests as real
        self.exceptions = real.exceptions
        self.tree = tree if tree is not None else TREE
        self.gets = []
        self.token_calls = 0
        self._token_ok, self._token_status = token_ok, token_status

    def post(self, url, **kwargs):
        self.token_calls += 1
        if not self._token_ok:
            return _Resp({}, ok=False, status=self._token_status)
        return _Resp({"access_token": f"tok{self.token_calls}",
                      "expires_in": 3600})

    def get(self, url, **kwargs):
        self.gets.append(url)
        return _Resp(self.tree[url])


# ------------------------------------------------------------- parsing -----

def test_a_block_is_not_a_diagnosis():
    """Most of ICD-11 is scaffolding and must not reach a doctor's picker.

    Chapters and blocks organise the classification; WHO omits ``code`` for
    them. Storing them would offer "Certain infectious or parasitic diseases"
    as something to write on a child's file.
    """
    from app.utils import icd_who
    assert icd_who.entity_code(TREE["u/1A00"]) == "1A00"
    assert icd_who.entity_code(TREE["u/ch1"]) is None
    assert icd_who.entity_code({"code": "   "}) is None


def test_titles_come_back_as_characters_not_markup():
    """WHO's titles carry HTML entities because a browser renders them.

    A picker showing "Certain infectious &amp; parasitic diseases" is a picker
    that looks broken to the person reading it.
    """
    from app.utils import icd_who
    assert icd_who.entity_title(TREE["u/ch1"]) == \
        "Certain infectious & parasitic diseases"


def test_flatten_keeps_one_row_per_code():
    """The classification is a graph, so a naive walk repeats itself.

    Without this, the same diagnosis appears twice in the picker a few rows
    apart, which reads as two different things.
    """
    from app.utils import icd_who
    pairs = icd_who.flatten([TREE["u/1A00"], TREE["u/ch1"], TREE["u/1A00"]])
    assert pairs == [("1A00", "Cholera")]


# ---------------------------------------------------------------- walk -----

def test_a_node_reachable_twice_is_fetched_once():
    """Both the request count and the result depend on this.

    ``1A00`` hangs under two chapters. Without the visited set it is fetched
    again — and so is everything beneath it, which on the real classification
    means thousands of duplicated requests against a free service.
    """
    from app.utils import icd_who
    fake = FakeWho()
    session = icd_who.Session({"client_id": "a", "client_secret": "b",
                               "release": ""}, requests=fake)
    icd_who.POLITE_DELAY = 0
    entities = icd_who.walk(session, start=ROOT)
    assert len(fake.gets) == len(set(fake.gets)) == 6
    assert len(entities) == 6


def test_the_walk_reports_progress():
    """Because it takes minutes, and a spinner with no number reads as a hang."""
    from app.utils import icd_who
    seen = []
    session = icd_who.Session({"client_id": "a", "client_secret": "b",
                               "release": ""}, requests=FakeWho())
    icd_who.POLITE_DELAY = 0
    icd_who.walk(session, start=ROOT, on_progress=seen.append)
    assert seen == [1, 2, 3, 4, 5, 6]


def test_the_token_is_fetched_once_for_a_whole_walk():
    """Thousands of requests must not mean thousands of token requests."""
    from app.utils import icd_who
    fake = FakeWho()
    session = icd_who.Session({"client_id": "a", "client_secret": "b",
                               "release": ""}, requests=fake)
    icd_who.POLITE_DELAY = 0
    icd_who.walk(session, start=ROOT)
    assert fake.token_calls == 1


def test_an_expired_token_is_replaced_mid_walk():
    """A full import outlives WHO's one-hour token.

    Without this the walk dies at minute sixty-one with a bare 401, after the
    clinic has already waited an hour — the kind of failure people give up on
    rather than report.
    """
    from app.utils import icd_who
    fake = FakeWho()
    session = icd_who.Session({"client_id": "a", "client_secret": "b",
                               "release": ""}, requests=fake)
    session.token()
    session._expires_at = 0          # as if an hour had passed
    session.token()
    assert fake.token_calls == 2


# -------------------------------------------------------------- import -----

@pytest.fixture()
def who_clinic(clinic):
    with clinic["app"].app_context():
        from app.models import Setting
        Setting.set("icd11_client_id", "cid")
        Setting.set("icd11_client_secret", "sec")
        clinic["db"].session.commit()
    yield clinic
    # Never leave an imported classification behind: it is gitignored, but a
    # later test asserting "ICD-11 is not loaded" would fail against it.
    from app.utils import icd
    path = icd._FULL["11"]
    if os.path.exists(path):
        os.remove(path)
    icd._full_cache.clear()


def test_importing_makes_the_option_appear(who_clinic):
    """The fix for the original bug, stated as the thing that used to be false.

    The picker asks what is loaded. Before the import ICD-11 is not offered;
    after it, it is — with no other change anywhere.
    """
    from app.utils import icd, icd_who
    with who_clinic["app"].app_context():
        assert icd.available_versions() == ["10"]
        icd_who.POLITE_DELAY = 0
        result = icd_who.import_all(requests=FakeWho())
        assert result == {"ok": True, "codes": 3}
        icd._full_cache.clear()
        assert icd.available_versions() == ["10", "11"]
        assert icd.search_icd("cholera", version="11")[0]["code"] == "1A00"


def test_the_blocks_do_not_survive_the_import(who_clinic):
    """End to end, not just in ``flatten``: three codes from six entities."""
    from app.utils import icd, icd_who
    with who_clinic["app"].app_context():
        icd_who.POLITE_DELAY = 0
        icd_who.import_all(requests=FakeWho())
        icd._full_cache.clear()
        found = icd.search_icd("infectious", version="11")
        assert found == []


def test_nothing_is_written_when_the_walk_yields_no_codes(who_clinic):
    """A half-written classification is worse than none.

    The doctor would get *some* results and no reason at all to suspect the
    rest was missing — which is the failure this whole feature exists to avoid.
    """
    from app.utils import icd, icd_who
    empty = {ROOT: {"@id": "root", "title": {"@value": "MMS"}, "child": []}}
    with who_clinic["app"].app_context():
        icd_who.POLITE_DELAY = 0
        result = icd_who.import_all(requests=FakeWho(tree=empty))
        assert result == {"ok": False, "error": "who_empty"}
        assert not os.path.exists(icd._FULL["11"])


def test_wrong_credentials_are_named_not_numbered(who_clinic):
    """"HTTP 400" tells a clinic nothing they can act on.

    A mistyped secret is by far the commonest failure and the only one they
    can fix themselves, so it is the one that gets its own sentence.
    """
    from app.utils import icd_who
    with who_clinic["app"].app_context():
        result = icd_who.test_connection(
            requests=FakeWho(token_ok=False, token_status=400))
        assert result == {"ok": False, "error": "who_bad_credentials"}


def test_no_credentials_is_a_different_answer_from_wrong_ones(clinic):
    """"You have not set this up" and "your keys are wrong" are not the same
    problem, and a clinic told the wrong one looks in the wrong place."""
    from app.utils import icd_who
    with clinic["app"].app_context():
        assert icd_who.test_connection() == {"ok": False,
                                             "error": "who_not_configured"}
        assert icd_who.import_all() == {"ok": False,
                                        "error": "who_not_configured"}


def test_a_network_failure_never_escapes_as_an_exception(who_clinic):
    """The import runs in a request; an unhandled error is a 500 page.

    A clinic that presses "download" with the internet down should be told the
    internet is down, on the settings screen they were already looking at.
    """
    from app.utils import icd_who

    class Dead(FakeWho):
        def post(self, url, **kwargs):
            raise self.exceptions.ConnectionError("no route to host")

    with who_clinic["app"].app_context():
        result = icd_who.import_all(requests=Dead())
        assert result["ok"] is False
        assert "network" in result["error"]


# ------------------------------------------------------------- the UI ------

def test_the_doctor_is_not_offered_a_classification_that_is_empty(clinic):
    """The original bug, at the screen where a doctor met it."""
    with clinic["app"].app_context():
        from app.models import Patient, User, Visit
        db = clinic["db"]
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        patient = db.session.get(Patient, clinic["ids"]["child"])
        visit = Visit(patient_id=patient.id, doctor_id=doctor.id,
                      visit_date=__import__("datetime").date.today())
        db.session.add(visit)
        db.session.commit()
        visit_id = visit.id

    body = (clinic["sign_in"]("doc").get(f"/visits/{visit_id}/record")
            .get_data(as_text=True))
    assert '<option value="11">ICD-11</option>' not in body
    assert 'name="icd_version" value="10"' in body


def test_the_settings_screen_states_what_is_loaded(clinic):
    """So an empty search is explained before it happens, not after."""
    body = clinic["sign_in"]("boss").get("/settings/",
                                         follow_redirects=True).get_data(as_text=True)
    assert "71,787" in body            # ICD-10, bundled
    assert "لسه متنزّلش" in body        # ICD-11, said plainly
    assert "icd.who.int/icdapi" in body
