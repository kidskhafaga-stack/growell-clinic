"""Counts for BigQuery — ``REPORTS_PLAN.md`` ت-٥.

«أرقام مجمّعة بس (من غير أسماء ولا أرقام ملفات)، بقرار المستشفى وبعد الرأي
القانوني». What is held:

* it is shut until the administrator records the hospital's decision and
  the legal opinion, both by reference; withdrawn, it shuts again;
* only the administrator reaches it;
* only counts per day leave — no name, no file number, no diagnosis code;
* a small count of people is held back, and so is money that fewer
  payments than the threshold make up;
* the file is the shape Google's documentation describes: one JSON object
  per line, a schema that is a JSON array of name/type/mode;
* every step is in the activity log, and the reports page has its door.
"""
import io
import json
import os
import sys
import zipfile
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def counted(clinic):
    """Six more visits today (the clinic already has one: seven), five with
    an asthma code and one with a rash; a payment of 200."""
    from app.extensions import db
    from app.models import Diagnosis, Invoice, Payment, Visit

    with clinic["app"].app_context():
        ids = clinic["ids"]
        for i in range(6):
            v = Visit(patient_id=ids["child"], doctor_id=ids["doctor"],
                      visit_date=local_today())
            db.session.add(v)
            db.session.flush()
            code = "J45.9" if i < 5 else "L20.9"
            db.session.add(Diagnosis(visit_id=v.id, code=code, title="تشخيص"))
        inv = Invoice(invoice_number="INV-BQ", patient_id=ids["child"],
                      invoice_date=local_today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(Payment(invoice_id=inv.id, amount=200, method="cash",
                               kind="payment"))
        db.session.commit()
    return clinic


def _open(c):
    return c["sign_in"]("boss").post("/reports/bigquery", data={
        "action": "decide", "hospital_ref": "محضر ١٢",
        "legal_ref": "مذكرة المستشار ٣"})


def _zip(c):
    today = local_today().isoformat()
    resp = c["sign_in"]("boss").get(
        f"/reports/bigquery/export?start={today}&end={today}")
    assert resp.status_code == 200, resp.status_code
    z = zipfile.ZipFile(io.BytesIO(resp.data))
    return z, [json.loads(line) for line in
               z.read("data.json").decode("utf-8").splitlines()]


def test_shut_until_the_decision_is_on_record(counted):
    today = local_today().isoformat()
    boss = counted["sign_in"]("boss")
    page = boss.get("/reports/bigquery").get_data(as_text=True)
    assert 'data-bqx="closed"' in page
    assert boss.get(f"/reports/bigquery/export?start={today}&end={today}") \
        .status_code == 403
    # A decision with no legal opinion does not open it.
    boss.post("/reports/bigquery", data={"action": "decide",
                                         "hospital_ref": "محضر ١٢"})
    assert 'data-bqx="closed"' in boss.get("/reports/bigquery") \
        .get_data(as_text=True)
    _open(counted)
    page = boss.get("/reports/bigquery").get_data(as_text=True)
    assert 'data-bqx="open"' in page and "مذكرة المستشار ٣" in page
    boss.post("/reports/bigquery", data={"action": "withdraw"})
    assert boss.get(f"/reports/bigquery/export?start={today}&end={today}") \
        .status_code == 403


def test_only_the_administrator(counted):
    for who in ("doc", "desk"):
        resp = counted["sign_in"](who).get("/reports/bigquery")
        assert resp.status_code in (302, 403), who


def test_only_counts_leave_and_small_ones_are_held_back(counted):
    from app.extensions import db
    from app.models import Patient

    _open(counted)
    z, rows = _zip(counted)
    raw = z.read("data.json").decode("utf-8")
    with counted["app"].app_context():
        kid = db.session.get(Patient, counted["ids"]["child"])
        # No name, no file number, no diagnosis code.
        for secret in (kid.full_name, kid.patient_number, "J45", "L20"):
            assert secret not in raw, secret
    got = {(r["measure"], r["dimension"]): r for r in rows}
    # Five asthma diagnoses reach the threshold of five; the one rash does not.
    assert got[("diagnoses", "J")]["value"] == 5
    rash = got[("diagnoses", "L")]
    assert (rash["value"], rash["suppressed"]) == (None, True)
    assert got[("visits", "clinic")]["value"] == 7
    # One family's payment on a day is that family's bill: held back too.
    money = got[("money_taken", "cash")]
    assert (money["value"], money["suppressed"]) == (None, True)


def test_the_file_is_the_shape_bigquery_reads(counted):
    import re

    _open(counted)
    z, rows = _zip(counted)
    assert sorted(z.namelist()) == ["README.txt", "data.json", "schema.json"]
    schema = json.loads(z.read("schema.json"))
    assert isinstance(schema, list)
    for col in schema:
        assert {"name", "type"} <= set(col)
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col["name"])
    names = [c["name"] for c in schema]
    assert all(set(r) == set(names) for r in rows)
    assert "--source_format=NEWLINE_DELIMITED_JSON" in \
        z.read("README.txt").decode("utf-8")


def test_the_threshold_is_the_clinics(counted):
    counted["sign_in"]("boss").post("/reports/bigquery", data={
        "action": "settings", "min_cell": "8", "site": "branch-02"})
    _open(counted)
    _z, rows = _zip(counted)
    got = {(r["measure"], r["dimension"]): r for r in rows}
    assert got[("visits", "clinic")]["suppressed"] is True     # 7 < 8
    assert {r["site"] for r in rows} == {"branch-02"}


def test_logged_and_has_its_door(counted):
    from app.models import ActivityLog

    _open(counted)
    _zip(counted)
    with counted["app"].app_context():
        actions = {a.action for a in ActivityLog.query.all()}
    assert {"bq_export.open", "bq_export.download"} <= actions
    index = counted["sign_in"]("boss").get("/reports/").get_data(as_text=True)
    assert "/reports/bigquery" in index
    # A period over a year is refused.
    start = (local_today() - timedelta(days=400)).isoformat()
    resp = counted["sign_in"]("boss").get(
        f"/reports/bigquery/export?start={start}&end={local_today()}")
    assert resp.status_code == 302


def test_money_from_enough_payments_leaves(counted):
    """Five payments make the day's cash figure — it leaves."""
    from app.extensions import db
    from app.models import Invoice, Payment

    with counted["app"].app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-BQ").one()
        for _ in range(4):
            db.session.add(Payment(invoice_id=inv.id, amount=100,
                                   method="cash", kind="payment"))
        db.session.commit()
    _open(counted)
    _z, rows = _zip(counted)
    got = {(r["measure"], r["dimension"]): r for r in rows}
    money = got[("money_taken", "cash")]
    assert (money["value"], money["suppressed"]) == (600.0, False)
