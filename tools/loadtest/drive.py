"""A working clinic, then a clinic twice as busy, then until it breaks.

    python -m tools.loadtest.drive loadtest.db --out results/
        [--threads 8] [--busy-ms 15000] [--stages 1,2,4,8,16]
        [--stage-seconds 60] [--port 5099]

Starts the clinic's own server (``serve.py``: waitress, production config)
on a copy ``fake_clinic`` built, and sends it people doing their day's work
over real HTTP, each from their own address, with the time a person takes
between clicks:

* **reception** — looks a child up, registers a new one, books them in as a
  walk-in, looks at the day's list;
* **doctor** — takes the next child waiting for them, opens the visit, writes
  it up, writes a drug, sends the child out;
* **cashier** — takes the next child the doctors sent out and collects;
* **board** — the screen on the wall, doing what the real one does: asking
  the cheap fingerprint (``/appointments/poll``) every twelve seconds, and
  drawing the whole board again only when the answer changes.

* **nurse**, **ward_doctor**, **pharmacist**, **lab** — on a hospital copy
  (``fake_clinic --profile hospital``): the vitals round and a dose, the
  ward round, checking a drug order, taking a sample and writing its result.

Stage 1 is the normal mix — for a clinic 2 reception, 3 doctors, 1 cashier,
2 boards; for a hospital, what a hospital of that size has on a weekday
morning (``MIXES``).
Each next stage multiplies everybody, until the slowest twentieth of
responses passes ``--give-up-p95`` seconds or more than 5% fail — and then
it stops, because the question is **how it breaks**, not whether.

Then it checks nothing was half-written: every booking that said "done" is
a booking, every checkout that said "done" is an invoice with its lines and
its money, and every write-up and drug is where the doctor left it.

It refuses to run on any database ``fake_clinic`` did not build.
"""
import argparse
import json
import os
import queue
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

import requests

MARKER = "LOADTEST"      # written into every visit and drug the test saves
MIXES = {
    "clinic": (("reception", 2), ("doctor", 3), ("cashier", 1), ("board", 2)),
    "hospital": (("reception", 6), ("doctor", 12), ("cashier", 3),
                 ("board", 6), ("nurse", 12), ("ward_doctor", 4),
                 ("pharmacist", 2), ("lab", 2)),
}
MIX = MIXES["clinic"]


def account(role, k, profile):
    """Which of the copy's accounts the ``k``-th person in a role signs in
    with — several people share one where the copy has fewer accounts."""
    from tools.loadtest.fake_clinic import PROFILES

    size = PROFILES[profile]
    if role == "reception":
        return f"reception{k % size['reception'] + 1}"
    if role in ("doctor", "ward_doctor"):
        return f"doctor{k % size['doctors'] + 1}"
    if role == "cashier":
        n = k % size["cashiers"] + 1
        return "cashier" if n == 1 else f"cashier{n}"
    if role in ("nurse", "lab"):
        return f"nurse{k % size['nurses'] + 1}"
    if role == "pharmacist":
        return f"pharmacist{k % size['pharmacists'] + 1}"
    return "admin"


def profile_of(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM settings WHERE key = ?",
                          ("load_test_profile",)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        con.close()
    return row[0] if row and row[0] in MIXES else "clinic"
CSRF = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"|'
                  r'<meta name="csrf-token" content="([^"]+)"')


# ------------------------------------------------------------ the copy ----
def is_a_copy(path):
    """Only a file ``fake_clinic`` stamped. Anything else is refused."""
    if not os.path.exists(path):
        return False
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM settings WHERE key = ?",
                          ("load_test_copy",)).fetchone()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return bool(row and row[0] == "1")


class Harness:
    """What the people in the test share: the day's list, who is waiting for
    which doctor, who is waiting to pay — and every response, timed."""

    def __init__(self, db, base):
        self.db, self.base = db, base
        self.lock = threading.Lock()
        self.records = []
        self.stage = 0
        self.waiting = defaultdict(deque)   # doctor username -> (appt, patient)
        self.taken = set()
        self.to_pay = queue.Queue()
        self.done = defaultdict(list)       # what said "done", to check after
        self.stop = threading.Event()
        con = self._ro()
        self.doctor_ids = {name: uid for uid, name in con.execute(
            "SELECT id, username FROM users WHERE username LIKE 'doctor%'")}
        self.service_id = con.execute(
            "SELECT id FROM services WHERE name = 'كشف'").fetchone()[0]
        self.names = [r[0].split()[0] for r in con.execute(
            "SELECT full_name FROM patients LIMIT 400")]
        self.max_appt_seen = 0
        # The wards, when there are any: the children in beds, and the work
        # waiting on them — each drug order given once, each checked once,
        # each blood taken and resulted once, however many people are at it.
        try:
            self.admissions = con.execute(
                "SELECT id, patient_id FROM admissions "
                "WHERE discharged_at IS NULL").fetchall()
            orders = con.execute(
                "SELECT id, admission_id FROM medication_orders "
                "WHERE stopped_at IS NULL ORDER BY id").fetchall()
            bloods = [r[0] for r in con.execute(
                "SELECT id FROM visit_investigations "
                "WHERE status = 'requested' AND kind = 'lab' ORDER BY id")]
        except sqlite3.OperationalError:
            self.admissions, orders, bloods = [], [], []
        self.pools = {"dose": deque(orders), "verify": deque(orders),
                      "lab": deque(bloods)}
        con.close()
        self.refresh()

    def _ro(self):
        return sqlite3.connect(f"file:{self.db}?mode=ro", uri=True,
                               timeout=30)

    def refresh(self):
        """Pick up children newly waiting — booked in by reception during the
        test — the way a doctor sees them appear on the board."""
        con = self._ro()
        try:
            rows = con.execute(
                "SELECT a.id, a.patient_id, a.doctor_id FROM appointments a "
                "WHERE a.appt_date = (SELECT MAX(appt_date) FROM appointments) "
                "AND a.status = 'waiting' AND a.id > ? ORDER BY a.id",
                (self.max_appt_seen,)).fetchall()
        except sqlite3.OperationalError:
            return
        finally:
            con.close()
        by_id = {v: k for k, v in self.doctor_ids.items()}
        with self.lock:
            for appt, patient, doctor in rows:
                self.max_appt_seen = max(self.max_appt_seen, appt)
                if appt not in self.taken and doctor in by_id:
                    self.waiting[by_id[doctor]].append((appt, patient))

    def next_for(self, doctor):
        with self.lock:
            pool = self.waiting[doctor]
            while pool:
                appt, patient = pool.popleft()
                if appt not in self.taken:
                    self.taken.add(appt)
                    return appt, patient
        return None

    def take(self, pool):
        with self.lock:
            return self.pools[pool].popleft() if self.pools[pool] else None

    def record(self, role, action, status, ms, kind):
        with self.lock:
            self.records.append({"stage": self.stage, "role": role,
                                 "action": action, "status": status,
                                 "ms": ms, "error": kind,
                                 "at": time.time()})


# ------------------------------------------------------------ a person ----
class Person(threading.Thread):
    """One member of staff at one machine."""

    def __init__(self, harness, role, username, address, password):
        super().__init__(daemon=True)
        self.h, self.role, self.username = harness, role, username
        self.password = password
        self.http = requests.Session()
        # Each person at their own machine — the rate limiter and the audit
        # log both key on the address, and a clinic is not one computer.
        self.http.headers["X-Forwarded-For"] = address
        self.token = None
        self.rnd = random.Random(hash((username, address)))

    # -- plumbing --
    def call(self, action, method, path, **kw):
        kw.setdefault("allow_redirects", False)
        kw.setdefault("timeout", 120)
        started = time.perf_counter()
        kind = None
        status = 0
        body = ""
        try:
            reply = self.http.request(method, self.h.base + path, **kw)
            status = reply.status_code
            body = reply.text if "text" in reply.headers.get(
                "Content-Type", "") or "json" in reply.headers.get(
                "Content-Type", "") else ""
        except requests.RequestException as exc:
            kind = "connection"
            body = str(exc)
            reply = None
        ms = (time.perf_counter() - started) * 1000
        if kind is None:
            if "database is locked" in body:
                kind = "locked"
            elif status >= 500:
                kind = "server_error"
            elif status == 429:
                kind = "rate_limited"
            elif status in (301, 302, 303) and "/login" in reply.headers.get(
                    "Location", ""):
                kind = "signed_out"
            elif status == 403 and "read_only" in body:
                kind = "read_only"
        self.h.record(self.role, action, status, ms, kind)
        if reply is not None:
            found = CSRF.search(body or "")
            if found:
                self.token = found.group(1) or found.group(2)
        return reply, kind

    def think(self, low, high):
        self.h.stop.wait(self.rnd.uniform(low, high))

    def sign_in(self):
        self.call("login_page", "GET", "/login")
        reply, kind = self.call("login", "POST", "/login", data={
            "username": self.username, "password": self.password,
            "csrf_token": self.token or ""})
        self.call("home", "GET", "/")
        return kind is None and reply is not None and reply.status_code in (302, 303)

    def post(self, action, path, data):
        data = dict(data, csrf_token=self.token or "")
        return self.call(action, "POST", path, data=data)

    # -- the day's work --
    def run(self):
        if not self.sign_in():
            return
        work = getattr(self, "as_" + self.role)
        while not self.h.stop.is_set():
            try:
                work()
            except Exception as exc:  # noqa: BLE001 - one bad step, keep going
                self.h.record(self.role, "harness", 0, 0, "harness:" +
                              type(exc).__name__)
                self.think(1, 2)

    def as_board(self):
        # `gcLivePoll` on the board page: the fingerprint every 12 s, the
        # page only when it moved. This used to fetch the whole board every
        # ten seconds, which is not what a wall screen does, and it counted
        # the page's cost against every tick.
        reply, kind = self.call("board_poll", "GET", "/appointments/poll")
        fingerprint = None
        if kind is None and reply is not None and reply.status_code == 200:
            try:
                fingerprint = reply.json().get("fp")
            except ValueError:
                fingerprint = None
        if fingerprint is None or fingerprint != getattr(self, "seen", None):
            self.call("board", "GET", "/appointments/")
            self.seen = fingerprint
        self.think(11, 13)

    def as_reception(self):
        self.call("patient_search", "GET", "/patients/?q=" +
                  self.rnd.choice(self.h.names))
        self.think(2, 5)
        reply, kind = self.call(
            "register_child", "POST", "/appointments/patient-quick",
            json={"full_name": f"{MARKER} {self.rnd.randint(1, 10**6)}",
                  "gender": self.rnd.choice(("male", "female")),
                  "date_of_birth": "2022-03-0" + str(self.rnd.randint(1, 9))},
            headers={"X-CSRFToken": self.token or ""})
        patient = None
        if kind is None and reply is not None and reply.status_code == 200:
            try:
                patient = reply.json()["patient"]["id"]
                self.h.done["register_child"].append(patient)
            except (ValueError, KeyError, TypeError):
                patient = None
        self.think(2, 4)
        if patient:
            doctor = self.rnd.choice(sorted(self.h.doctor_ids))
            reply, kind = self.post("walk_in", "/appointments/walk-in", {
                "patient_id": patient, "doctor_id": self.h.doctor_ids[doctor],
                "reason": MARKER})
            if kind is None and reply is not None and reply.status_code in (302, 303):
                self.h.done["walk_in"].append(patient)
        self.call("board", "GET", "/appointments/")
        self.think(4, 10)

    def as_doctor(self):
        nxt = self.h.next_for(self.username)
        if nxt is None:
            self.call("board", "GET", "/appointments/")
            self.think(5, 8)
            return
        appt, patient = nxt
        reply, kind = self.call("open_visit", "GET",
                                f"/visits/start/{patient}?appointment_id={appt}")
        if kind or reply is None or reply.status_code not in (302, 303):
            return
        found = re.search(r"/visits/(\d+)/record", reply.headers.get("Location", ""))
        if not found:
            return
        visit = int(found.group(1))
        self.call("visit_page", "GET", f"/visits/{visit}/record")
        self.think(5, 12)                     # examining, typing
        reply, kind = self.post("write_visit", f"/visits/{visit}/record", {
            "chief_complaint": f"{MARKER} حرارة", "clinical_exam": "حلق أحمر",
            "plan": "راحة وسوائل", "notes": ""})
        if kind is None and reply is not None and reply.status_code in (302, 303):
            self.h.done["write_visit"].append(visit)
        self.think(2, 5)
        reply, kind = self.post("write_drug", f"/visits/{visit}/medications", {
            "name": f"{MARKER} باراسيتامول", "dose": "5 مل",
            "frequency": "كل ٦ ساعات", "duration": "٣ أيام"})
        if kind is None and reply is not None and reply.status_code in (302, 303):
            self.h.done["write_drug"].append(visit)
        self.think(1, 3)
        reply, kind = self.post("send_out", f"/appointments/{appt}/status",
                                {"status": "completed"})
        if kind is None and reply is not None and reply.status_code in (302, 303):
            self.h.to_pay.put(appt)
        self.think(2, 4)

    # -- the wards --
    def _saved(self, reply, kind):
        return (kind is None and reply is not None
                and reply.status_code in (302, 303))

    def as_nurse(self):
        self.call("ward_board", "GET", "/ward/")
        if not self.h.admissions:
            self.think(10, 20)
            return
        admission, patient = self.rnd.choice(self.h.admissions)
        self.call("chart", "GET", f"/beds/admission/{admission}")
        self.think(5, 10)                      # at the bedside
        reply, kind = self.post("record_obs",
                                f"/observations/patient/{patient}/record", {
                                    "temperature_c": "37.8", "pulse_bpm": "118",
                                    "resp_rate": "30", "spo2": "96",
                                    "note": MARKER})
        if self._saved(reply, kind):
            self.h.done["record_obs"].append(patient)
        self.think(3, 8)
        order = self.h.take("dose")
        if order:
            reply, kind = self.post("give_dose",
                                    f"/beds/medication/{order[0]}/dose",
                                    {"outcome": "given", "note": MARKER})
            if self._saved(reply, kind):
                self.h.done["give_dose"].append(order[0])
        self.think(15, 30)

    def as_ward_doctor(self):
        self.call("ward_board", "GET", "/ward/")
        if not self.h.admissions:
            self.think(10, 20)
            return
        admission, _patient = self.rnd.choice(self.h.admissions)
        self.call("chart", "GET", f"/beds/admission/{admission}")
        self.think(10, 20)                     # reading the chart
        reply, kind = self.post("round", f"/beds/admission/{admission}/round", {
            "trend": "stable", "assessment": f"{MARKER} مستقر",
            "plan": "نفس العلاج"})
        if self._saved(reply, kind):
            self.h.done["round"].append(admission)
        self.think(20, 40)

    def as_pharmacist(self):
        self.call("pharmacy_ward", "GET", "/pharmacy/ward")
        order = self.h.take("verify")
        if not order:
            self.think(10, 20)
            return
        self.call("pharmacy_chart", "GET", f"/pharmacy/ward/{order[1]}")
        self.think(5, 10)
        reply, kind = self.post("verify", f"/pharmacy/order/{order[0]}/verify",
                                {})
        if self._saved(reply, kind):
            self.h.done["verify"].append(order[0])
        self.think(5, 15)

    def as_lab(self):
        self.call("lab_bench", "GET", "/labs/")
        blood = self.h.take("lab")
        if not blood:
            self.think(10, 20)
            return
        reply, kind = self.post("collect", f"/labs/order/{blood}/collect",
                                {"code": f"S{blood}"})
        if not self._saved(reply, kind):
            return
        self.think(10, 20)                     # on the analyser
        reply, kind = self.post("result", f"/labs/order/{blood}/result", {
            "result_value": "11.2", "result_unit": "g/dL",
            "result_low": "11", "result_high": "14"})
        if self._saved(reply, kind):
            self.h.done["result"].append(blood)
        self.think(5, 10)

    def as_cashier(self):
        try:
            appt = self.h.to_pay.get(timeout=5)
        except queue.Empty:
            self.call("cashier_home", "GET", "/finance/cashier")
            return
        self.call("checkout_page", "GET", f"/finance/checkout/{appt}")
        self.think(3, 6)
        reply, kind = self.post("collect", f"/finance/checkout/{appt}", {
            "line_desc": "كشف", "line_service_id": self.h.service_id,
            "line_price": "250", "line_qty": "1",
            "amount": "250", "method": "cash"})
        found = re.search(r"/invoices/(\d+)/receipt",
                          reply.headers.get("Location", "") if reply is not None else "")
        if kind is None and found:
            # The invoice the till says it wrote — checked afterwards by its
            # own number, not guessed from the appointment: a child seen
            # twice in a day has one invoice for the day, by design.
            self.h.done["collect"].append((appt, int(found.group(1)), 250))
        self.think(2, 4)


# ------------------------------------------------------------ numbers ----
def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round(p / 100 * len(values))) - 1))
    return values[k]


def summarise(records, seconds):
    ms = [r["ms"] for r in records if r["action"] != "harness"]
    errors = defaultdict(int)
    for r in records:
        if r["error"]:
            errors[r["error"]] += 1
    by_action = defaultdict(list)
    for r in records:
        by_action[r["action"]].append(r["ms"])
    return {
        "requests": len(ms),
        "per_second": round(len(ms) / seconds, 2) if seconds else None,
        "p50_ms": round(pct(ms, 50) or 0), "p95_ms": round(pct(ms, 95) or 0),
        "max_ms": round(max(ms) if ms else 0),
        "errors": dict(errors),
        "error_rate": round(sum(errors.values()) / len(ms), 4) if ms else 0,
        "actions": {a: {"n": len(v), "p50_ms": round(pct(v, 50)),
                        "p95_ms": round(pct(v, 95)), "max_ms": round(max(v))}
                    for a, v in sorted(by_action.items()) if v},
    }


def integrity(db, done, started_at):
    """Was anything that said "done" not done — or done by half?"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    out = {}
    try:
        walk = set(done.get("walk_in", []))
        booked = {r[0] for r in con.execute(
            "SELECT patient_id FROM appointments WHERE is_walk_in = 1 "
            "AND reason = ?", (MARKER,))}
        out["walk_in"] = {"said_done": len(walk), "missing": len(walk - booked)}
        registered = set(done.get("register_child", []))
        present = {r[0] for r in con.execute(
            "SELECT id FROM patients WHERE full_name LIKE ?", (MARKER + " %",))}
        out["register_child"] = {"said_done": len(registered),
                                 "missing": len(registered - present)}
        written = set(done.get("write_visit", []))
        kept = {r[0] for r in con.execute(
            "SELECT id FROM visits WHERE chief_complaint LIKE ?",
            (MARKER + "%",))}
        out["write_visit"] = {"said_done": len(written),
                              "missing": len(written - kept)}
        drugs = done.get("write_drug", [])
        rows = con.execute("SELECT COUNT(*) FROM visit_medications WHERE name "
                           "LIKE ?", (MARKER + "%",)).fetchone()[0]
        out["write_drug"] = {"said_done": len(drugs),
                             "missing": max(0, len(drugs) - rows)}
        paid = done.get("collect", [])
        wanted = defaultdict(float)          # invoice -> money the till took
        for _appt, invoice, amount in paid:
            wanted[invoice] += amount
        rows = {}
        for invoice in wanted:
            rows[invoice] = con.execute(
                "SELECT (SELECT COALESCE(SUM(unit_price * quantity), 0) "
                "        FROM invoice_items WHERE invoice_id = i.id), "
                "       (SELECT COALESCE(SUM(amount), 0) FROM payments "
                "        WHERE invoice_id = i.id), "
                "       (SELECT COUNT(*) FROM journal_entries "
                "        WHERE source_type = 'invoice' AND source_id = i.id) "
                "FROM invoices i WHERE i.id = ?", (invoice,)).fetchone()
        present = {k: v for k, v in rows.items() if v is not None}
        journal_on = any(v[2] for v in present.values())
        # Two invoices for one appointment — the double charge a double
        # click or a retry could make.
        twice = con.execute(
            "SELECT COUNT(*) FROM (SELECT appointment_id FROM invoices "
            "WHERE appointment_id IS NOT NULL AND created_at >= ? "
            "GROUP BY appointment_id HAVING COUNT(*) > 1)",
            (started_at,)).fetchone()[0]
        out["collect"] = {
            "said_done": len(paid),
            "invoices": len(wanted),
            "missing": len(wanted) - len(present),
            "twice": twice,
            "no_lines": len([v for v in present.values() if not v[0]]),
            # What the till said it took, against what the invoice holds.
            "money_not_matching": len([k for k, v in present.items()
                                       if round(v[1] - wanted[k], 2) != 0
                                       or round(v[0] - v[1], 2) != 0]),
            "journal_on": journal_on,
            "no_journal": (len([v for v in present.values() if not v[2]])
                           if journal_on else None),
        }
        _ward_integrity(con, done, out)
    finally:
        con.close()
    return out


def _ward_integrity(con, done, out):
    """The ward's work, checked the same way: said saved, and there."""
    if not any(done.get(k) for k in ("record_obs", "give_dose", "round",
                                     "verify", "result")):
        return
    obs = done.get("record_obs", [])
    rows = con.execute("SELECT COUNT(*) FROM observations WHERE note = ?",
                       (MARKER,)).fetchone()[0]
    out["record_obs"] = {"said_done": len(obs),
                         "missing": max(0, len(obs) - rows)}
    given = set(done.get("give_dose", []))
    there = {r[0] for r in con.execute(
        "SELECT order_id FROM medication_doses WHERE note = ?", (MARKER,))}
    out["give_dose"] = {"said_done": len(given),
                        "missing": len(given - there)}
    rounds = done.get("round", [])
    rows = con.execute("SELECT COUNT(*) FROM round_notes WHERE assessment "
                       "LIKE ?", (MARKER + "%",)).fetchone()[0]
    out["round"] = {"said_done": len(rounds),
                    "missing": max(0, len(rounds) - rows)}
    checked = set(done.get("verify", []))
    there = {r[0] for r in con.execute(
        "SELECT id FROM medication_orders WHERE verified_at IS NOT NULL")}
    out["verify"] = {"said_done": len(checked),
                     "missing": len(checked - there)}
    resulted = set(done.get("result", []))
    there = {r[0] for r in con.execute(
        "SELECT id FROM visit_investigations WHERE status = 'resulted'")}
    out["result"] = {"said_done": len(resulted),
                     "missing": len(resulted - there)}


def ledger_gaps(db):
    """What the journal is missing after the run, read the way the journal
    screen reads it (``app.utils.ledger_gaps``)."""
    os.environ["DATABASE_URL"] = "sqlite:///" + db
    from app import create_app
    from app.utils import ledger_gaps as gaps

    app = create_app("testing")
    with app.app_context():
        return {k: len(v) for k, v in gaps.missing().items()}


# ------------------------------------------------------------ the run ----
def start_server(db, port, threads, busy_ms, log_path):
    env = dict(os.environ, SQLITE_BUSY_TIMEOUT_MS=str(busy_ms),
               FLASK_CONFIG="production")
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.loadtest.serve", db, str(port),
         str(threads)], env=env, stdout=log, stderr=subprocess.STDOUT,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if requests.get(base + "/login", timeout=2).status_code == 200:
                return proc, base
        except requests.RequestException:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("the server did not start — see " + log_path)


def run(db, out, threads=8, busy_ms=15000, stages=(1, 2, 4, 8, 16),
        stage_seconds=60, port=5099, give_up_p95=10.0, password=None):
    from tools.loadtest.fake_clinic import PASSWORD

    db = os.path.abspath(db)
    if not is_a_copy(db):
        raise SystemExit(f"refused: {db} is not a copy fake_clinic built")
    os.makedirs(out, exist_ok=True)
    password = password or PASSWORD
    server_log = os.path.join(out, "server.log")
    proc, base = start_server(db, port, threads, busy_ms, server_log)
    started_at = datetime.utcnow().isoformat(sep=" ")
    profile = profile_of(db)
    mix = MIXES[profile]
    h = Harness(db, base)
    results = {"config": {"threads": threads, "busy_ms": busy_ms,
                          "stage_seconds": stage_seconds, "cpus": os.cpu_count(),
                          "db_mb": round(os.path.getsize(db) / 2**20, 1),
                          "profile": profile, "mix": dict(mix)},
               "stages": []}
    refresher_stop = threading.Event()

    def refresher():
        while not refresher_stop.wait(3):
            h.refresh()

    threading.Thread(target=refresher, daemon=True).start()
    address = 0
    broke = None
    try:
        for n, mult in enumerate(stages, start=1):
            h.stage = n
            h.stop.clear()
            people = []
            for role, count in mix:
                for k in range(count * mult):
                    address += 1
                    name = account(role, k, profile)
                    people.append(Person(h, role, name,
                                         f"10.{address // 250}.{address % 250}.9",
                                         password))
            for p in people:
                p.start()
                time.sleep(0.05)
            began = time.time()
            h.stop.wait(stage_seconds)
            h.stop.set()
            for p in people:
                p.join(timeout=150)
            took = time.time() - began
            rows = [r for r in h.records if r["stage"] == n]
            stage = summarise(rows, took)
            stage.update({"stage": n, "multiplier": mult, "people": len(people)})
            results["stages"].append(stage)
            print(f"stage {n} ×{mult}: {len(people)} people · "
                  f"{stage['requests']} requests · p95 {stage['p95_ms']} ms · "
                  f"errors {stage['errors']}", flush=True)
            if (stage["p95_ms"] > give_up_p95 * 1000
                    or stage["error_rate"] > 0.05):
                broke = n
                break
    finally:
        refresher_stop.set()
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    results["broke_at_stage"] = broke
    results["integrity"] = integrity(db, h.done, started_at)
    with open(server_log, errors="replace") as f:
        text = f.read()
    results["server_log"] = {"tracebacks": text.count("Traceback"),
                             "database_is_locked": text.count("database is locked")}
    results["done"] = {k: len(v) for k, v in h.done.items()}
    results["ledger_gaps"] = ledger_gaps(db)
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("db")
    parser.add_argument("--out", default="loadtest-results")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--busy-ms", type=int, default=15000)
    parser.add_argument("--stages", default="1,2,4,8,16")
    parser.add_argument("--stage-seconds", type=int, default=60)
    parser.add_argument("--port", type=int, default=5099)
    parser.add_argument("--give-up-p95", type=float, default=10.0)
    args = parser.parse_args(argv)
    results = run(args.db, args.out, threads=args.threads,
                  busy_ms=args.busy_ms,
                  stages=tuple(int(s) for s in args.stages.split(",")),
                  stage_seconds=args.stage_seconds, port=args.port,
                  give_up_p95=args.give_up_p95)
    print(json.dumps(results["integrity"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
