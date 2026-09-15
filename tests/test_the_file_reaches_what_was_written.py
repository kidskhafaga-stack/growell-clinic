"""The record has to be able to produce what the record already holds.

> **GAHAR IMT.08**, fifth item of evidence: *"The patient's medical record is
> **available when needed** by a healthcare professional."*

`docs/gahar/record_contents_matrix.md` sorts the gaps in the file into three
kinds, and this is the first: **work that was done, paid for, and reachable
from nowhere on the record.** It is the cheapest to close and the only one
where the failure is purely a missing door.

Three doors here:

* **Investigations had no tab.** The curves — a line per test across every
  visit — were drawn at the top of the *visits* tab, which is a list of
  encounters; so a cross-visit view lived inside one. And the orders
  themselves were visible one encounter at a time, so «ورّيني تحاليل الطفل
  ده» meant opening visits until you found them. An order still waiting, the
  one somebody has to chase, appeared nowhere at all.
* **The discharge summary was reachable only from the stay screen** of a stay
  that had already ended — which nobody opens again six months later. ACT.15
  asks for *a copy kept in the patient's medical record*, and a summary the
  record cannot produce is not in the record.
* And the curves are **moved, not copied**: two drawings of one reading is
  two chances to disagree.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def file_of(clinic):
    """A child with a lab that came back, a scan being done elsewhere, and a
    stay that ended with a summary."""
    from app.models import Setting, VisitInvestigation, Visit
    from app.models.admission import Admission
    from app.models.discharge_summary import DischargeSummary
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        # The stays tab only exists where there is a ward — see
        # `_ward_context`, which answers «you never made a ward» differently
        # from «every bed is taken».
        Setting.set("mod_enabled:beds", "1")
        kid = clinic["ids"]["child"]
        visit = Visit(patient_id=kid, doctor_id=clinic["ids"]["doctor"],
                      visit_date=local_today())
        db.session.add(visit)
        db.session.flush()
        db.session.add_all([
            VisitInvestigation(visit_id=visit.id, patient_id=kid, kind="lab",
                               name="صورة دم", status="resulted",
                               result_value=11.2, result_unit="g/dL"),
            VisitInvestigation(visit_id=visit.id, patient_id=kid,
                               kind="imaging", name="إيكو على القلب",
                               status="requested", done_outside=True,
                               outside_place="مركز النيل"),
        ])
        stay = Admission(patient_id=kid, admitted_at=local_today())
        db.session.add(stay)
        db.session.flush()
        # Two of the six written elements filled, so the link has to read
        # «ناقص ٤ بنود» — a summary that exists and is not finished.
        db.session.add(DischargeSummary(admission_id=stay.id, patient_id=kid,
                                        diagnosis="التهاب رئوي",
                                        followup="متابعة بعد أسبوع"))
        db.session.commit()
        clinic["stay"] = stay.id
    return clinic


def _file(clinic):
    return clinic["sign_in"]().get(
        "/patients/%s" % clinic["ids"]["child"]).get_data(as_text=True)


# ------------------------------------------------ the investigations tab ---
def test_the_file_has_a_tab_for_investigations(file_of):
    page = _file(file_of)

    assert "tab==='labs'" in page


def test_every_order_is_on_it_answered_or_not(file_of):
    """**Not only the ones that came back.** An order still waiting is the one
    somebody has to chase, and a list of answers cannot show what is
    missing."""
    page = _file(file_of)

    assert "data-lab-orders" in page
    assert "صورة دم" in page
    assert "إيكو على القلب" in page
    assert 'data-order-state="requested"' in page
    assert 'data-order-state="resulted"' in page


def test_a_scan_being_done_elsewhere_says_so_and_where(file_of):
    page = _file(file_of)

    assert "مركز النيل" in page


def test_the_result_is_on_the_row(file_of):
    page = _file(file_of)

    assert "11.2" in page
    assert "g/dL" in page


def test_the_curves_moved_and_were_not_copied(file_of):
    """Two drawings of one reading is two chances to disagree — the argument
    this file already makes about the device studies."""
    from app.utils import lab_series

    page = _file(file_of)
    with file_of["app"].app_context():
        # The panel renders once, under the new tab and not under visits.
        before_labs = page.split("tab==='labs'")[0]
        assert "lab_curves" not in before_labs
        assert lab_series.every_order(file_of["ids"]["child"])


def test_the_orders_reader_is_newest_first(file_of):
    from app.utils import lab_series

    with file_of["app"].app_context():
        rows = lab_series.every_order(file_of["ids"]["child"])

    assert [r.name for r in rows] == ["إيكو على القلب", "صورة دم"]


def test_a_child_with_nothing_gets_a_sentence_not_an_empty_table(clinic):
    from app.i18n import _load_translations, _lookup

    page = clinic["sign_in"]().get(
        "/patients/%s" % clinic["ids"]["child"]).get_data(as_text=True)
    with clinic["app"].app_context():
        said = _lookup(_load_translations(), "ar", "patients.no_labs")

    assert "data-lab-orders" not in page
    assert said in page


def test_the_reader_answers_nothing_for_a_child_with_no_orders(clinic):
    from app.utils import lab_series

    with clinic["app"].app_context():
        assert lab_series.every_order(clinic["ids"]["child"]) == []


# ------------------------------------------------- the discharge summary ---
def test_the_summary_is_reachable_from_the_file(file_of):
    """**ACT.15's third item of evidence**: *a copy of the discharge summary
    is kept in the patient's medical record*. It was built in full and
    reachable only from the screen of a stay that had already ended."""
    page = _file(file_of)

    assert "data-stay-summary" in page
    assert "#discharge-summary" in page


def test_the_link_says_whether_it_is_finished(file_of):
    """«كامل» and «ناقص ٣ بنود» are two different next steps for whoever
    opens it."""
    from app.i18n import _load_translations, _lookup

    page = _file(file_of)
    with file_of["app"].app_context():
        tables = _load_translations()
        short = _lookup(tables, "ar", "summary.short").split("{")[0].strip()

    assert short in page


def test_the_anchor_it_points_at_exists(file_of):
    """A link to a fragment the target page does not carry scrolls nowhere."""
    stay = file_of["sign_in"]().get(
        "/beds/admission/%s" % file_of["stay"]).get_data(as_text=True)

    assert 'id="discharge-summary"' in stay


def test_a_stay_with_no_summary_offers_no_link(file_of):
    """«مفيش ملخّص» is a fact about the stay, not a broken button."""
    from app.models.admission import Admission
    from app.utils.clock import local_today

    with file_of["app"].app_context():
        db = file_of["db"]
        db.session.add(Admission(patient_id=file_of["ids"]["child"],
                                 admitted_at=local_today()))
        db.session.commit()

    # One stay has a summary and one does not: exactly one link.
    assert _file(file_of).count("data-stay-summary") == 1


# ------------------------------------------- and only this child's --------
@pytest.fixture()
def other_child(file_of):
    """A second child, with an order and a stay summary of their own.

    **The fixture the first draft did not have.** With one patient on file,
    dropping the `patient_id` filter from either reader changes nothing and
    every test still passes — and what it would ship is another child's
    investigations and another child's discharge summary printed on this
    one's record. A mutation found both.
    """
    from app.models import Patient, Visit, VisitInvestigation
    from app.models.admission import Admission
    from app.models.discharge_summary import DischargeSummary
    from app.utils.clock import local_today

    with file_of["app"].app_context():
        db = file_of["db"]
        other = Patient(patient_number="P-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today())
        db.session.add(other)
        db.session.flush()
        visit = Visit(patient_id=other.id, doctor_id=file_of["ids"]["doctor"],
                      visit_date=local_today())
        db.session.add(visit)
        db.session.flush()
        db.session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=other.id, kind="lab",
            name="تحليل الطفل التاني", status="resulted"))
        stay = Admission(patient_id=other.id, admitted_at=local_today())
        db.session.add(stay)
        db.session.flush()
        db.session.add(DischargeSummary(admission_id=stay.id,
                                        patient_id=other.id,
                                        diagnosis="تشخيص الطفل التاني"))
        db.session.commit()
        file_of["other"] = other.id
    return file_of


def test_another_childs_investigations_are_not_on_this_file(other_child):
    from app.utils import lab_series

    page = _file(other_child)
    with other_child["app"].app_context():
        mine = lab_series.every_order(other_child["ids"]["child"])

    assert "تحليل الطفل التاني" not in page
    assert [r.name for r in mine] == ["إيكو على القلب", "صورة دم"]


def test_another_childs_discharge_summary_is_not_on_this_file(other_child):
    """The summaries are looked up by stay, and a stay belongs to a child.
    Reading them all and keying by `admission_id` would put the other
    child's summary under this child's stay only if the ids collided — so
    the real harm is the count, and the count is what this asserts."""
    from app.blueprints.patients.routes import _discharge_summaries

    with other_child["app"].app_context():
        mine = _discharge_summaries(other_child["ids"]["child"])
        theirs = _discharge_summaries(other_child["other"])

    assert len(mine) == 1
    assert len(theirs) == 1
    assert set(mine) & set(theirs) == set()


# ------------------------------------------------------ the operations tab -
@pytest.fixture()
def operated(clinic):
    """A child with two operations: one written up short, one not at all."""
    from app.models import Setting
    from app.models.operative_report import OperativeReport
    from app.models.theatre import Operation, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        room = Theatre(name="غرفة ١")
        db.session.add(room)
        db.session.flush()
        written = Operation(patient_id=clinic["ids"]["child"],
                            theatre_id=room.id, procedure="استئصال زائدة",
                            on_date=local_today(),
                            surgeon_id=clinic["ids"]["doctor"])
        blank = Operation(patient_id=clinic["ids"]["child"],
                          theatre_id=room.id, procedure="ختان",
                          on_date=local_today())
        db.session.add_all([written, blank])
        db.session.flush()
        db.session.add(OperativeReport(operation_id=written.id,
                                       pre_diagnosis="التهاب زائدة"))
        db.session.commit()
    return clinic


def test_operations_have_a_tab_of_their_own(operated):
    """They were a few lines at the bottom of *overview* — an operative
    history filed beside the phone number, on the tab reception opens."""
    page = _file(operated)

    assert "tab==='operations'" in page
    assert "استئصال زائدة" in page
    assert "ختان" in page


def test_the_tab_says_whether_anybody_wrote_the_case_up(operated):
    """**`SAS.08` asks for the report to be kept in the medical record**, and
    the file could say an operation happened without being able to say
    whether anybody had written it up."""
    page = _file(operated)

    assert 'data-report-state="short"' in page
    assert 'data-report-state="none"' in page


def test_a_half_written_report_says_how_many_are_left(operated):
    """«ناقص ٤ بنود» and «مفيش تقرير» are two different errands.

    The count itself is asserted, not merely «there is a digit» — a mutation
    that made the number always nought passed that, and «ناقص ٠ بنود» is a
    sentence that tells a registrar to go and do nothing.
    """
    import re

    from app.blueprints.patients.routes import _report_missing
    from app.models.theatre import Operation

    page = _file(operated)
    said = re.search(r'data-report-state="short">([^<]*)<', page)
    with operated["app"].app_context():
        op = Operation.query.filter_by(procedure="استئصال زائدة").one()
        left = _report_missing(op)

    assert left == 4, "one of the five written elements was filled"
    assert said and str(left) in said.group(1)


def test_the_list_left_the_overview_tab(operated):
    """Moved, not copied — the same rule the curves follow above."""
    page = _file(operated)
    before = page.split("tab==='operations'")[0]

    assert "data-operations" not in before


def test_a_child_with_no_operations_gets_no_tab(clinic):
    """A tab labelled «عمليات» on the file of a child who has never had one
    is furniture, and most of this clinic's files are those."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:theatres", "1")
        clinic["db"].session.commit()

    assert "tab==='operations'" not in _file(clinic)


def test_the_tab_says_whether_the_anaesthetic_was_planned(operated):
    """**SAS.16 EOC 2** asks for *a detailed plan for anesthesia care* and
    names six elements. The file could say a child was anaesthetised without
    being able to say whether anybody planned it."""
    from app.models.theatre import AnaesthesiaPlan, Operation

    with operated["app"].app_context():
        db = operated["db"]
        op = (Operation.query.filter_by(procedure="استئصال زائدة").one())
        db.session.add(AnaesthesiaPlan(operation_id=op.id, kind="general",
                                       induction="بروبوفول", airway="أنبوبة",
                                       fluids="محلول ملح"))
        db.session.commit()

    page = _file(operated)

    assert 'data-plan-state="planned"' in page
    assert 'data-plan-state="none"' in page


def test_only_the_four_that_belong_before_the_case_count_as_missing(operated):
    """What was given during the anaesthetic and what went wrong are an
    account of what happened — empty beforehand is not a gap, and a plan
    marked short for them would be the checklist problem in another shape."""
    from app.blueprints.patients.routes import _plan_state
    from app.models.theatre import AnaesthesiaPlan, Operation

    with operated["app"].app_context():
        db = operated["db"]
        op = Operation.query.filter_by(procedure="ختان").one()
        db.session.add(AnaesthesiaPlan(operation_id=op.id, kind="local",
                                       induction="موضعي", airway="طبيعي",
                                       fluids="مفيش"))
        db.session.commit()

        # `given_during` and `events` are both empty and it is still planned.
        assert _plan_state(op) == "planned"


def test_a_plan_missing_one_of_the_four_reads_as_short(operated):
    from app.blueprints.patients.routes import _plan_state
    from app.models.theatre import AnaesthesiaPlan, Operation

    with operated["app"].app_context():
        db = operated["db"]
        op = Operation.query.filter_by(procedure="ختان").one()
        db.session.add(AnaesthesiaPlan(operation_id=op.id, kind="local",
                                       induction="موضعي", airway="طبيعي"))
        db.session.commit()

        assert _plan_state(op) == "short"


def test_a_case_with_no_plan_says_so(operated):
    from app.blueprints.patients.routes import _plan_state
    from app.models.theatre import Operation

    with operated["app"].app_context():
        op = Operation.query.filter_by(procedure="ختان").one()

        assert _plan_state(op) == "none"
        assert _plan_state(None) == "none"
