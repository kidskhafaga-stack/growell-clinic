"""The lab's own screens: the rack, one order, and the list of tests.

**The doctor already had a door and the lab had none.** Ordering has worked
from the visit screen for years, and reading a result has its own inbox. What
had no screen anywhere was the middle — the person who walks to the bed with a
tube, and the person who runs it — so a hospital's lab ran on a paper list
beside a program that already knew every order on it.

Three screens and no more:

* **the rack** — everything ordered and not answered, longest-waiting first,
  split into what needs drawing and what needs running, because those are two
  jobs done by two people;
* **one order** — draw it, or write the answer on it;
* **the tests** — the catalogue, with what each is charged as. Admin only,
  like every other list that decides what things cost.
"""
import json
from datetime import datetime

from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.labs import labs_bp
from app.extensions import db
from app.i18n import t
from app.models import Investigation, VisitInvestigation
# Still both kinds here, and rightly: the **catalogue** screen lists
# every investigation the clinic offers and `add_test` creates either.
# What stopped being two kinds is the *rack* — see `index`.
from app.models.prescription import INVESTIGATION_KINDS
from app.utils import lab_results
from app.utils import labs as bench
from app.utils.decorators import module_required

MODULE = "labs"


@labs_bp.route("/")
@module_required(MODULE)
def index():
    """The rack — **the lab's, and only the lab's**.

    It used to read a `kind` off the query string and default it to `None`,
    which is «every kind»: the bench's own screen listed every echocardiogram
    in the building beside the blood counts, counted them under «to collect»,
    and offered a «sample taken» button on them. Reported as «ليه ركويست
    الايكو موجود فى المعمل؟».

    There is no kind here now, because this screen is one of them. Scans have
    their own screen, with their own verb — see `app/blueprints/imaging`.
    """
    state = (request.args.get("state") or "").strip() or None
    if state not in bench.OPEN_STATES:
        state = None
    rows = bench.worklist(kind=bench.LAB, state=state)
    return render_template("labs/index.html",
                           rows=rows, state=state,
                           # Where the child is, when they are in a bed: the
                           # sample is drawn at the bed, not at the desk.
                           beds=bench.beds_of(rows),
                           counts=bench.counts(bench.LAB), bench=bench,
                           # On the door to the scans, so a rack that no
                           # longer lists them still says they are there.
                           imaging_open=sum(
                               bench.counts(bench.IMAGING).values()),
                           diagnostic_open=sum(
                               bench.counts(bench.DIAGNOSTIC).values()),
                           now=datetime.utcnow(),
                           late=lab_results.late,
                           critical_open=len(lab_results.all_waiting()),
                           may_build=current_user.is_admin)


@labs_bp.route("/order/<int:order_id>")
@module_required(MODULE)
def order(order_id):
    """One order: what was asked for, where it is, and the box for the answer."""
    row = db.get_or_404(VisitInvestigation, order_id)
    # A test the laboratory has broken into what it measures is answered
    # line by line, each against this child's range; one it has not is
    # answered the way it always was.
    lines = lab_results.sheet(row) if lab_results.measured(row) else None
    return render_template("labs/order.html", order=row, bench=bench,
                           lines=lines, late=lab_results.late(row),
                           age_days=lab_results.age_days(
                               row.patient, row.collected_at or row.created_at),
                           may_read=lab_results.reads_results(current_user),
                           waited=bench.waiting_minutes(row))


@labs_bp.route("/order/<int:order_id>/collect", methods=["POST"])
@module_required(MODULE)
def collect(order_id):
    """The sample was taken."""
    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        bench.collect(row, user=current_user, code=request.form.get("code"))
    except ValueError:
        db.session.rollback()
        # Which refusal it was: an order that already has an answer is a
        # keystroke on the wrong row, and saying "no" without saying why sends
        # somebody to draw blood a second time to find out.
        flash(t("lab.already_resulted"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    db.session.commit()
    flash(t("lab.collected", code=row.sample_code), "success")
    return redirect(request.referrer or url_for("labs.index"))


@labs_bp.route("/order/<int:order_id>/result", methods=["POST"])
@module_required(MODULE)
def result(order_id):
    """The answer, written on the order it answers."""
    row = db.get_or_404(VisitInvestigation, order_id)
    if lab_results.measured(row):
        return _result_by_analyte(row)
    bench.record(row,
                 value=_number(request.form.get("result_value")),
                 unit=request.form.get("result_unit"),
                 low=_number(request.form.get("result_low")),
                 high=_number(request.form.get("result_high")),
                 text=request.form.get("result_text") or "",
                 comment=None, user=current_user)
    db.session.commit()
    flash(t("lab.resulted") if row.status == bench.RESULTED
          else t("lab.result_cleared"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


def _result_by_analyte(row):
    """The answer as the laboratory prints it: one value per analyte."""
    from app.models import ActivityLog

    entries = {}
    for key, raw in request.form.items():
        if key.startswith("a_") and key[2:].isdigit():
            entries[int(key[2:])] = raw
    was_critical = row.critical_at is not None
    critical = lab_results.save(row, entries, user=current_user,
                                text=request.form.get("result_text") or "")
    if critical and not was_critical:
        # Kept in the log as well as on the order: a critical value that was
        # later corrected leaves the order clean, and the log is where «was
        # anybody told» is still answerable.
        ActivityLog.record(
            "lab.critical", user_id=current_user.id,
            entity="visit_investigation", entity_id=row.id,
            detail=json.dumps([{"analyte": v.analyte.name, "value": v.shown(),
                                "flag": v.flag} for v in critical],
                              ensure_ascii=False))
    db.session.commit()
    if critical:
        flash(t("lab_result.critical_saved", n=len(critical)), "warning")
    else:
        flash(t("lab.resulted") if row.status == bench.RESULTED
              else t("lab.result_cleared"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/critical")
@module_required(MODULE)
def critical():
    """Critical values nobody has read yet — the lab's list to chase, and a
    doctor's own at the top."""
    rows = lab_results.all_waiting()
    mine = set(lab_results.critical_for(current_user))
    rows.sort(key=lambda r: (r.id not in mine, r.critical_at))
    return render_template("labs/critical.html", rows=rows, mine=mine,
                           beds=bench.beds_of(rows), now=datetime.utcnow(),
                           may_read=lab_results.reads_results(current_user))


@labs_bp.route("/order/<int:order_id>/critical-read", methods=["POST"])
@module_required(MODULE)
def critical_read(order_id):
    """A doctor has read the critical value on this order."""
    from app.models import ActivityLog

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_results.mark_read(row, current_user)
    except PermissionError:
        abort(403, description=t("lab_result.only_a_doctor"))
    except ValueError:
        flash(t("lab_result.nothing_critical"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    ActivityLog.record("lab.critical_read", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id)
    db.session.commit()
    flash(t("lab_result.read_saved"), "success")
    if request.form.get("back") == "list":
        return redirect(url_for("labs.critical"))
    return redirect(url_for("labs.order", order_id=row.id))


# ------------------------------------------------------------- the tests ---
#: How many tests the list draws at once. A laboratory's catalogue runs to
#: hundreds, and each row is a form with the price list in it.
PAGE = 50


@labs_bp.route("/tests")
@module_required(MODULE)
def tests():
    """The catalogue, and what each test is charged as — searched, and a page
    at a time, because a laboratory's list is hundreds long."""
    _admin_only()
    from sqlalchemy import or_

    from app.models.service import Service

    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    page = max(1, request.args.get("page", type=int) or 1)
    query = Investigation.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Investigation.name_ar.ilike(like),
                                 Investigation.name_en.ilike(like),
                                 Investigation.aliases.ilike(like),
                                 Investigation.code.ilike(like)))
    if category:
        query = query.filter(Investigation.category == category)
    total = query.count()
    rows = (query.order_by(Investigation.kind, Investigation.name_ar)
            .offset((page - 1) * PAGE).limit(PAGE).all())
    categories = [c for (c,) in db.session.query(Investigation.category)
                  .filter(Investigation.category.isnot(None))
                  .distinct().order_by(Investigation.category).all()]
    return render_template(
        "labs/tests.html", rows=rows, kinds=INVESTIGATION_KINDS,
        q=q, category=category, categories=categories, page=page,
        pages=max(1, -(-total // PAGE)), total=total,
        reference=_reference_state(rows),
        services=(Service.query.filter(Service.is_active.is_(True))
                  .order_by(Service.name).all()))


def _reference_state(rows):
    """``{test id: {"analytes", "ranges", "drafts"}}`` for the page's rows, in
    one query — the line under each test that says what the laboratory has
    told us about it."""
    from app.models import LabRange, LabTestAnalyte

    ids = [r.id for r in rows]
    if not ids:
        return {}
    out = {i: {"analytes": 0, "ranges": 0, "drafts": 0} for i in ids}
    links = (db.session.query(LabTestAnalyte.investigation_id,
                              LabTestAnalyte.analyte_id)
             .filter(LabTestAnalyte.investigation_id.in_(ids)).all())
    by_analyte = {}
    for test_id, analyte_id in links:
        out[test_id]["analytes"] += 1
        by_analyte.setdefault(analyte_id, []).append(test_id)
    if by_analyte:
        for analyte_id, approved in (db.session.query(LabRange.analyte_id,
                                                      LabRange.approved_at)
                                     .filter(LabRange.analyte_id.in_(
                                         list(by_analyte))).all()):
            for test_id in by_analyte[analyte_id]:
                out[test_id]["ranges"] += 1
                if approved is None:
                    out[test_id]["drafts"] += 1
    return out


# ------------------------------------------------ bringing a list in -------
@labs_bp.route("/tests/import", methods=["GET", "POST"])
@module_required(MODULE)
def import_tests():
    """«استيراد» — the laboratory's sheet, read and shown before anything is
    written. The lab module's own door, and the only one: a clinic without
    the module never reaches it, and the catalogue a clinic is given on
    install and update is not touched by it."""
    _admin_only()
    from app.utils import lab_import

    if request.method == "GET":
        return render_template("labs/import.html", plan=None)
    upload = request.files.get("sheet")
    if upload is None or not (upload.filename or "").lower().endswith(".xlsx"):
        flash(t("lab_import.need_xlsx"), "error")
        return redirect(url_for("labs.import_tests"))
    try:
        plan = lab_import.read(upload.stream)
    except Exception:  # noqa: BLE001 — a sheet a person made can be anything
        flash(t("lab_import.unreadable"), "error")
        return redirect(url_for("labs.import_tests"))
    if not plan["tests"]:
        flash(t("lab_import.nothing_found"), "error")
        return redirect(url_for("labs.import_tests"))
    return redirect(url_for("labs.import_preview",
                            token=lab_import.keep(plan)))


@labs_bp.route("/tests/import/<token>", methods=["GET", "POST"])
@module_required(MODULE)
def import_preview(token):
    """What the sheet holds, what it meets in the catalogue, and what looked
    wrong — before a single row is written. The page's own «import» button
    posts back here (``_import_apply``)."""
    _admin_only()
    from app.models import Investigation as Inv
    from app.utils import lab_import

    if request.method == "POST":
        return _import_apply(token)
    plan = lab_import.load(token)
    if plan is None:
        flash(t("lab_import.expired"), "error")
        return redirect(url_for("labs.import_tests"))
    found = lab_import.match(plan)
    tests_by_key = {x["key"]: x for x in plan["tests"]}
    linked = set(found["auto"]) | {q["pick"] for q in found["questions"]
                                   if q["pick"]}
    fresh = [x for x in plan["tests"] if x["key"] not in linked]
    by_category = {}
    for test in fresh:
        name = test["category"] or "—"
        by_category[name] = by_category.get(name, 0) + 1
    ranges = [r for a in plan["analytes"].values() for r in a["ranges"]]
    return render_template(
        "labs/import.html", plan=plan, token=token, found=found,
        tests_by_key=tests_by_key,
        ours={row.id: row for row in Inv.query.filter(
            Inv.id.in_(list(found["auto"].values()) or [0])).all()},
        fresh=len(fresh), by_category=sorted(by_category.items(),
                                             key=lambda x: -x[1]),
        n_ranges=len(ranges),
        n_sourced=sum(1 for r in ranges if r["source"]),
        n_critical=sum(1 for r in ranges if r["critical_low"] is not None
                       or r["critical_high"] is not None),
        n_parts_missing=sum(1 for x in plan["tests"] if x["parts_missing"]),
        n_tat=sum(1 for x in plan["tests"] if x["tat"]),
        n_tube=sum(1 for x in plan["tests"] if x["tube"]))


def _import_apply(token):
    """Write what the preview showed, with the links as a person left them."""
    from app.models import ActivityLog
    from app.utils import lab_import
    from app.utils.decorators import client_ip

    plan = lab_import.load(token)
    if plan is None:
        flash(t("lab_import.expired"), "error")
        return redirect(url_for("labs.import_tests"))
    answers = {name[2:]: value for name, value in request.form.items()
               if name.startswith("q_")}
    links = lab_import.links_from(plan, answers)
    counts = lab_import.apply(plan, links, user=current_user,
                              show_new=request.form.get("show_new") == "1")
    ActivityLog.record("lab.import", user_id=current_user.id,
                       entity="investigation", entity_id=None,
                       detail=json.dumps(counts), ip_address=client_ip())
    db.session.commit()
    lab_import.forget(token)
    flash(t("lab_import.done", **counts), "success")
    return redirect(url_for("labs.tests"))


@labs_bp.route("/tests/export")
@module_required(MODULE)
def export_tests():
    """The catalogue as a sheet for the laboratory to complete and send back —
    the same columns the import reads."""
    _admin_only()
    import io

    from flask import send_file

    from app.utils import lab_import

    rows = (Investigation.query.filter(Investigation.kind == "lab")
            .order_by(Investigation.name_ar).all())
    return send_file(io.BytesIO(lab_import.export(rows)),
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet",
                     as_attachment=True, download_name="lab_tests.xlsx")


@labs_bp.route("/tests/<int:test_id>/ranges")
@module_required(MODULE)
def test_ranges(test_id):
    """What one test measures, and every range the laboratory has given for
    each — with where it came from and whether it is approved."""
    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    return render_template("labs/test_ranges.html", test=row)


@labs_bp.route("/tests/<int:test_id>/approve", methods=["POST"])
@module_required(MODULE)
def approve_ranges(test_id):
    """The laboratory's director approves this test's ranges. Until then they
    are a reference beside a result and never call it high or low."""
    _admin_only()
    from app.models import ActivityLog
    from app.utils import lab_import
    from app.utils.decorators import client_ip

    row = db.get_or_404(Investigation, test_id)
    done = lab_import.approve_test(row, current_user)
    ActivityLog.record("lab.ranges_approved", user_id=current_user.id,
                       entity="investigation", entity_id=row.id,
                       detail=str(done), ip_address=client_ip())
    db.session.commit()
    flash(t("lab_import.approved", n=done), "success")
    return redirect(url_for("labs.test_ranges", test_id=row.id))


@labs_bp.route("/tests/add", methods=["POST"])
@module_required(MODULE)
def add_test():
    _admin_only()
    name = (request.form.get("name_ar") or "").strip()[:160]
    if not name:
        flash(t("lab.need_name"), "error")
        return redirect(url_for("labs.tests"))
    kind = request.form.get("kind")
    db.session.add(Investigation(
        name_ar=name,
        name_en=(request.form.get("name_en") or "").strip()[:160] or None,
        kind=kind if kind in INVESTIGATION_KINDS else "lab",
        unit=(request.form.get("unit") or "").strip()[:20] or None,
        sample_type=(request.form.get("sample_type") or "").strip()[:40] or None,
        # Ticked by default on the add form, so a clinic that never touches
        # this box builds a catalogue of things it does — which is what a
        # catalogue has always meant here.
        in_house=request.form.get("in_house") == "1",
        service_id=request.form.get("service_id", type=int)))
    db.session.commit()
    flash(t("lab.test_added"), "success")
    return redirect(url_for("labs.tests"))


@labs_bp.route("/tests/<int:test_id>", methods=["POST"])
@module_required(MODULE)
def edit_test(test_id):
    """The unit, the sample, and the price. The name too — a clinic renames a
    test and every order already written keeps the name it was written with,
    because the order snapshots it."""
    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    name = (request.form.get("name_ar") or "").strip()[:160]
    if name:
        row.name_ar = name
    row.name_en = (request.form.get("name_en") or "").strip()[:160] or None
    row.unit = (request.form.get("unit") or "").strip()[:20] or None
    row.sample_type = (request.form.get("sample_type") or "").strip()[:40] or None
    # Cleared on purpose when the box is empty: a clinic that stops charging
    # for a test has to be able to say so, and an empty select means nobody
    # rather than "leave it as it was".
    row.service_id = request.form.get("service_id", type=int)
    row.is_active = request.form.get("is_active") == "1"
    # **«ما عندناش إيكو» — قالتها العيادة مرة واحدة.** A different question
    # from `is_active`: a test the clinic sends out still belongs in the
    # search, because the *order* is written here whoever performs it. All
    # this decides is whether the order joins this building's own worklist.
    row.in_house = request.form.get("in_house") == "1"
    db.session.commit()
    flash(t("lab.test_saved"), "success")
    return redirect(url_for("labs.tests"))


def _admin_only():
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))


def _number(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
