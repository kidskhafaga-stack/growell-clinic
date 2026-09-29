"""A survey that follows the answers: "if no, go to question 5".

Asked as: *«تقدر المؤسسة تضيف أسئلة وتخلّي أسئلة مرتبطة بأسئلة — لو نعم يروح
لأسئلة أكتر، لو لا كده»*, then on the prototype *«لو لا روح على السؤال
الفلاني»*, and a thank-you screen in the organisation's name with its logo.

What is held here:

* the five built-in questions keep their wording, their columns and their
  order; the clinic adds its own among them;
* a jump is written on an answer and goes forward or to the end — never back;
* a branch question is skipped unless an answer leads to it, and an answer to
  a question the family was never sent to is not kept — whatever the page sent;
* a question can be asked about one part of the clinic only;
* the builder refuses a backwards jump, drops the jumps to a question that is
  deleted, and switches off (rather than deletes) a question with answers;
* the thank-you says someone will call when a side was rated low, and offers
  the public review only to a family that scored 9 or 10.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import hospital  # noqa: E402,F401


def _feedback(clinic, token="tok", centre_id=None):
    from app.models import Feedback

    with clinic["app"].app_context():
        fb = Feedback(patient_id=clinic["ids"]["child"], token=token,
                      status="sent", cost_centre_id=centre_id)
        clinic["db"].session.add(fb)
        clinic["db"].session.commit()
        return fb.id


def _question(clinic, text, kind="yesno", options=None, branch_only=False,
              after=None, centres=None):
    """Add one of the clinic's own questions the way the builder does."""
    boss = clinic["sign_in"]("boss")
    boss.post("/messages/survey/questions/new", data={
        "text_ar": text, "kind": kind, "options_ar": options or "",
        "branch_only": "1" if branch_only else ""})
    from app.models import SurveyQuestion
    with clinic["app"].app_context():
        row = SurveyQuestion.query.filter_by(text_ar=text).one()
        if centres is not None:
            row.centre_keys = centres
            clinic["db"].session.commit()
        return row.id, row.key


def _jump(clinic, qid, **rules):
    data = {f"jump_{group}": to for group, to in rules.items()}
    from app.models import SurveyQuestion
    with clinic["app"].app_context():
        row = clinic["db"].session.get(SurveyQuestion, qid)
        if not row.builtin:
            data.update({"text_ar": row.text_ar, "kind": row.kind,
                         "options_ar": row.options_ar or "",
                         "branch_only": "1" if row.branch_only else "",
                         "is_active": "1"})
    clinic["sign_in"]("boss").post(f"/messages/survey/questions/{qid}", data=data)


def _builtin_id(clinic, key):
    from app.models import SurveyQuestion
    from app.utils import survey_flow
    with clinic["app"].app_context():
        survey_flow.ensure_seeded()
        clinic["db"].session.commit()
        return SurveyQuestion.query.filter_by(key=key).one().id


def _saved(clinic, token="tok"):
    from app.models import Feedback
    with clinic["app"].app_context():
        fb = Feedback.query.filter_by(token=token).one()
        return {"doctor": fb.doctor_rating, "finance": fb.finance_rating,
                "nps": fb.nps, "comment": fb.comment, "concerns": fb.concerns,
                "answers": json.loads(fb.answers or "{}")}


# ------------------------------------------------------------ the rules ---
def test_the_path_skips_branches_and_never_goes_back(clinic):
    from app.utils.survey_flow import path

    steps = [{"key": "a", "kind": "yesno", "branch_only": False, "jumps": {"no": "b"}},
             {"key": "b", "kind": "text", "branch_only": True, "jumps": {}},
             {"key": "c", "kind": "stars", "branch_only": False, "jumps": {"high": "end", "low": "a"}},
             {"key": "d", "kind": "text", "branch_only": False, "jumps": {}}]
    assert path(steps, {"a": "yes"}) == ["a", "c", "d"]
    assert path(steps, {"a": "no"}) == ["a", "b", "c", "d"]
    assert path(steps, {"a": "yes", "c": "5"}) == ["a", "c"]
    assert path(steps, {"a": "yes", "c": "1"}) == ["a", "c", "d"]    # not back


def test_the_answer_groups_have_their_edges_where_the_builder_says(clinic):
    from app.utils.survey_flow import bucket

    assert [bucket("stars", n) for n in (1, 2, 3, 4, 5)] == [
        "low", "low", "mid", "high", "high"]
    assert [bucket("nps", n) for n in (0, 6, 7, 8, 9, 10)] == [
        "low", "low", "mid", "mid", "high", "high"]
    assert (bucket("yesno", "maybe"), bucket("single", "x"), bucket("stars", "")) == (
        None, None, None)


def test_the_page_is_not_given_a_jump_to_a_question_it_does_not_ask(hospital):
    from app.models.place import Unit
    from app.utils import cost_centres

    first, _ = _question(hospital, "سؤال للكل")
    _, only_key = _question(hospital, "للعيادة بس", centres="outpatient",
                            branch_only=True)
    _jump(hospital, first, no=only_key)
    with hospital["app"].app_context():
        ward = cost_centres.for_unit(Unit.query.one())
        hospital["db"].session.commit()
        ward_id = ward.id
    _feedback(hospital, "ward", centre_id=ward_id)
    _feedback(hospital, "visit")
    public = hospital["app"].test_client()
    # As a quoted key, not as two letters: the page also carries random
    # tokens, and "q2" turns up inside one of them now and then.
    ward_page = public.get("/f/ward").get_data(as_text=True)
    assert f'&#34;{only_key}&#34;' not in ward_page and f'"{only_key}"' not in ward_page
    assert f'&#34;no&#34;: &#34;{only_key}&#34;' in public.get("/f/visit").get_data(as_text=True) \
        or f'"no": "{only_key}"' in public.get("/f/visit").get_data(as_text=True)


def test_the_built_in_survey_still_works_as_it_did(clinic):
    _feedback(clinic)
    page = clinic["app"].test_client().get("/f/tok").get_data(as_text=True)
    order = [page.index(f'data-step="{k}"') for k in ("doctor", "service", "finance", "nps", "comment")]
    assert order == sorted(order) and "data-q-finance" in page
    clinic["app"].test_client().post("/f/tok", data={
        "doctor_rating": "4", "finance_rating": "3", "nps": "8",
        "comment": "كويس", "concern": ["finance:price"]})
    got = _saved(clinic)
    assert (got["doctor"], got["finance"], got["nps"], got["comment"]) == (4, 3, 8, "كويس")
    assert got["concerns"] == "finance:price" and got["answers"] == {}


# --------------------------------------------------------- the clinic's own ---
def test_no_leads_to_the_branch_and_yes_passes_it(clinic):
    explain, explain_key = _question(clinic, "اتشرحتلكم الخطة؟")
    why, why_key = _question(clinic, "إيه اللي ما كانش واضح؟", kind="single",
                             options="التشخيص\nالأدوية", branch_only=True)
    _jump(clinic, explain, no=why_key)
    _feedback(clinic, "no")
    _feedback(clinic, "yes")
    page = clinic["app"].test_client().get("/f/no").get_data(as_text=True)
    assert f'data-step="{why_key}"' in page and 'data-branch="1"' in page
    public = clinic["app"].test_client()
    public.post("/f/no", data={f"a_{explain_key}": "no", f"a_{why_key}": "o1"})
    public.post("/f/yes", data={f"a_{explain_key}": "yes", f"a_{why_key}": "o1"})
    assert _saved(clinic, "no")["answers"] == {
        explain_key: {"q": "اتشرحتلكم الخطة؟", "a": "no"},
        why_key: {"q": "إيه اللي ما كانش واضح؟", "a": "الأدوية"}}
    # Passed by on "yes": what the page sent for the branch is not kept.
    assert _saved(clinic, "yes")["answers"] == {
        explain_key: {"q": "اتشرحتلكم الخطة؟", "a": "yes"}}


def test_a_jump_to_the_end_leaves_the_rest_unasked(clinic):
    finance = _builtin_id(clinic, "finance")
    _jump(clinic, finance, high="end")
    _feedback(clinic)
    clinic["app"].test_client().post("/f/tok", data={
        "doctor_rating": "5", "finance_rating": "5", "nps": "10",
        "comment": "لازم ما يتحفظش"})
    got = _saved(clinic)
    assert (got["finance"], got["nps"], got["comment"]) == (5, None, None)


def test_what_bothered_them_is_kept_only_for_a_side_they_were_asked(clinic):
    doctor = _builtin_id(clinic, "doctor")
    _jump(clinic, doctor, high="end")
    _feedback(clinic)
    clinic["app"].test_client().post("/f/tok", data={
        "doctor_rating": "5", "concern": ["doctor:late", "finance:price"]})
    assert _saved(clinic)["concerns"] == "doctor:late"


def test_a_question_asked_about_one_unit_only(hospital):
    from app.models.place import Unit
    from app.utils import cost_centres

    _question(hospital, "شرحولكم الرضاعة؟", centres="outpatient")
    with hospital["app"].app_context():
        ward = cost_centres.for_unit(Unit.query.one())
        hospital["db"].session.commit()
        ward_id = ward.id
    _feedback(hospital, "visit")
    _feedback(hospital, "ward", centre_id=ward_id)
    public = hospital["app"].test_client()
    assert "شرحولكم الرضاعة؟" in public.get("/f/visit").get_data(as_text=True)
    assert "شرحولكم الرضاعة؟" not in public.get("/f/ward").get_data(as_text=True)


# ----------------------------------------------------------- the builder ---
def test_only_an_admin_builds_it(clinic):
    assert clinic["sign_in"]("desk").get("/messages/survey/questions").status_code == 403
    assert clinic["sign_in"]("desk").post("/messages/survey/questions/new", data={
        "text_ar": "x"}).status_code == 403
    page = clinic["sign_in"]("boss").get("/messages/survey/questions").get_data(as_text=True)
    assert page.count("data-question=") == 5


def test_a_backwards_jump_is_not_kept_and_moving_drops_one(clinic):
    from app.models import SurveyQuestion

    first, first_key = _question(clinic, "أول")
    second, second_key = _question(clinic, "تاني")
    _jump(clinic, second, no=first_key)                    # backwards
    _jump(clinic, first, no=second_key)                    # forward
    with clinic["app"].app_context():
        assert clinic["db"].session.get(SurveyQuestion, second).jump_map() == {}
        assert clinic["db"].session.get(SurveyQuestion, first).jump_map() == {"no": second_key}
    # Moving the second above the first makes that jump point backwards.
    clinic["sign_in"]("boss").post(f"/messages/survey/questions/{second}/move",
                                   data={"dir": "up"})
    with clinic["app"].app_context():
        assert clinic["db"].session.get(SurveyQuestion, first).jump_map() == {}


def test_a_branch_nothing_leads_to_is_pointed_out(clinic):
    _, key = _question(clinic, "يتيم", branch_only=True)
    page = clinic["sign_in"]("boss").get("/messages/survey/questions").get_data(as_text=True)
    assert f'data-problem="orphan:{key}"' in page


def test_deleting_a_question_with_answers_switches_it_off(clinic):
    from app.models import SurveyQuestion

    asked, asked_key = _question(clinic, "مسئول")
    unasked, unasked_key = _question(clinic, "محدش جاوبه", branch_only=True)
    _jump(clinic, asked, no=unasked_key)
    _feedback(clinic)
    clinic["app"].test_client().post("/f/tok", data={f"a_{asked_key}": "yes"})
    boss = clinic["sign_in"]("boss")
    boss.post(f"/messages/survey/questions/{asked}/delete")
    boss.post(f"/messages/survey/questions/{unasked}/delete")
    with clinic["app"].app_context():
        row = clinic["db"].session.get(SurveyQuestion, asked)
        assert row is not None and row.is_active is False
        assert row.jump_map() == {}                 # the jump went with it
        assert clinic["db"].session.get(SurveyQuestion, unasked) is None
    # And a built-in cannot be deleted at all.
    assert boss.post(f"/messages/survey/questions/{_builtin_id(clinic, 'nps')}/delete").status_code == 400


# ---------------------------------------------------------- the thank-you ---
def test_the_thank_you_depends_on_what_they_said(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("survey_review_url", "https://g.page/r/example")
        Setting.set("clinic_logo", "logo.png")
        clinic["db"].session.commit()
    for token, form in (("sad", {"finance_rating": "2", "nps": "10"}),
                        ("glad", {"finance_rating": "5", "nps": "9"}),
                        ("meh", {"finance_rating": "4", "nps": "7"})):
        _feedback(clinic, token)
        clinic["app"].test_client().post(f"/f/{token}", data=form)
    public = clinic["app"].test_client()
    sad = public.get("/f/sad").get_data(as_text=True)
    glad = public.get("/f/glad").get_data(as_text=True)
    meh = public.get("/f/meh").get_data(as_text=True)
    assert "data-care" in sad and "data-review" not in sad
    assert "data-review" in glad and "g.page/r/example" in glad
    assert "data-review" not in meh and "data-care" not in meh
    assert "uploads/clinic/logo.png" in glad


def test_only_a_web_link_is_taken_as_the_review_link(clinic):
    from app.models import Setting

    clinic["sign_in"]("boss").post("/messages/survey", data={
        "survey_mode": "link", "survey_review_url": "javascript:alert(1)"})
    with clinic["app"].app_context():
        assert Setting.get("survey_review_url") == ""


def test_the_board_reads_the_clinics_own_questions(clinic):
    _, key = _question(clinic, "هترجعولنا؟")
    for n, answer in enumerate(("yes", "yes", "no")):
        _feedback(clinic, f"t{n}")
        clinic["app"].test_client().post(f"/f/t{n}", data={f"a_{key}": answer})
    page = clinic["sign_in"]("boss").get("/messages/satisfaction").get_data(as_text=True)
    assert f'data-own="{key}"' in page and "67%" in page


def test_the_preview_sends_nothing(clinic):
    page = clinic["sign_in"]("boss").get("/messages/survey/preview").get_data(as_text=True)
    assert "data-preview" in page and 'data-step="doctor"' in page
    assert clinic["sign_in"]("desk").get("/messages/survey/preview").status_code == 403
