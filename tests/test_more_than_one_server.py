"""More than one server process — ``WORKERS`` in clinic.env.

Chosen for the hospital: the load test found the whole program was one
Python process, running on one core however many threads it had, while the
other cores sat idle (``docs/LOAD_TEST.md``).

What is held here:

* **unset is how it always was** — one process, served exactly as before;
* the processes really do share one port, and look after each other: one
  that dies is started again, and when the first one goes — stopped
  properly or killed outright — nothing is left behind;
* what one process used to keep to itself is shared or handed over: the
  login limit is one limit, the WhatsApp queue is sent by one of them, the
  nightly backup is taken by one of them, and an update closes them all.
"""
import os
import re
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ------------------------------------------------------------ the setting ----
@pytest.mark.parametrize("written, count", [
    (None, 1), ("", 1), ("1", 1), ("4", 4), (" 3 ", 3), ("16", 16),
    ("0", 1), ("-2", 1), ("17", 1), ("four", 1), ("2.5", 1),
])
def test_how_many_it_asks_for(written, count):
    from app.utils.workers import chosen

    environ = {} if written is None else {"WORKERS": written}
    assert chosen(environ) == count


def test_unset_is_the_one_process_it_always_was(monkeypatch):
    """No ``WORKERS``: waitress on this process, as before; the several-
    process server is not started."""
    import run
    from app.utils import workers

    served = []
    monkeypatch.delenv("WORKERS", raising=False)
    monkeypatch.setattr("waitress.serve", lambda *a, **k: served.append(k))
    monkeypatch.setattr(workers, "serve_many",
                        lambda *a, **k: pytest.fail("started several"))
    run.serve(run.app, 5999)
    assert served and served[0]["threads"] == 8


def test_workers_set_starts_several(monkeypatch):
    import run
    from app.utils import workers

    asked = []
    monkeypatch.setenv("WORKERS", "3")
    monkeypatch.setattr("waitress.serve",
                        lambda *a, **k: pytest.fail("served alone"))
    monkeypatch.setattr(workers, "serve_many",
                        lambda port, count, **k: asked.append((port, count))
                        or 0)
    with pytest.raises(SystemExit):
        run.serve(run.app, 5999)
    assert asked == [(5999, 3)]


# ------------------------------------------------------------ the real thing ----
def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _children(pid):
    """Direct children of ``pid``, from /proc."""
    kids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if int(fields[1]) == pid:
            kids.append((int(entry), cmd))
    return kids


def _workers_of(pid):
    return sorted(k for k, cmd in _children(pid) if "spawn_main" in cmd)


def _alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _get(port, path="/login", headers=None, data=None, cookies=None):
    import http.cookiejar
    import urllib.error
    import urllib.parse
    import urllib.request

    jar = cookies if cookies is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=body, headers=dict(headers or {},
                                                             Connection="close"))
    try:
        reply = opener.open(request, timeout=20)
        return reply.status, reply.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


@pytest.fixture()
def several(tmp_path):
    """The load test's server with three workers, on a fresh database."""
    if not os.path.isdir("/proc"):
        pytest.skip("reads the process tree from /proc")
    db_path = tmp_path / "several.db"
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_path}",
               FLASK_CONFIG="production", PYTHONPATH=ROOT)
    env.pop("WORKERS", None)
    subprocess.run([sys.executable, "-c",
                    "from app import create_app; from app.extensions import db;"
                    "app = create_app('production');"
                    "ctx = app.app_context(); ctx.push(); db.create_all()"],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.loadtest.serve", str(db_path),
         str(port), "4", "3"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if _get(port)[0] == 200 and len(_workers_of(proc.pid)) == 3:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("the servers did not start")
    yield {"proc": proc, "port": port}
    if proc.poll() is None:
        proc.kill()
        proc.wait(10)


def test_three_processes_answer_one_port_and_look_after_each_other(several):
    master, port = several["proc"].pid, several["port"]
    first = _workers_of(master)
    assert len(first) == 3

    # One dies: it is started again, and the port never stopped answering.
    os.kill(first[0], 9)
    deadline = time.time() + 20
    while time.time() < deadline:
        now = _workers_of(master)
        if len(now) == 3 and first[0] not in now:
            break
        time.sleep(0.5)
    assert len(_workers_of(master)) == 3
    assert _get(port)[0] == 200

    # Stopped properly: every one of them goes with it.
    everyone = _workers_of(master)
    several["proc"].terminate()
    several["proc"].wait(30)
    time.sleep(2)
    assert not any(_alive(pid) for pid in everyone)


def test_killing_the_first_leaves_nothing_behind(several):
    """Closed from Task Manager, with no chance to tidy up: the workers see
    their lifeline break and go, rather than living on holding the port and
    the files an update is about to replace."""
    master = several["proc"].pid
    everyone = [pid for pid, _cmd in _children(master)]
    os.kill(master, 9)
    several["proc"].wait(10)
    deadline = time.time() + 20
    while time.time() < deadline and any(_alive(p) for p in everyone):
        time.sleep(0.5)
    assert not any(_alive(pid) for pid in everyone)


def test_the_login_limit_is_one_limit_across_them(several):
    """Ten wrong tries a minute from one machine, then refused — however
    the tries are spread over the workers. Four separate counts would have
    let a password guesser forty."""
    port = several["port"]
    codes = []
    for n in range(14):
        import http.cookiejar

        jar = http.cookiejar.CookieJar()
        headers = {"X-Forwarded-For": "10.7.7.7"}     # the test server believes it
        page = _get(port, headers=headers, cookies=jar)[1]
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
        codes.append(_get(port, headers=headers, cookies=jar, data={
            "username": f"nobody{n}", "password": "wrong",
            "csrf_token": token.group(1) if token else ""})[0])
    assert codes[:10] == [codes[0]] * 10 and codes[0] != 429
    assert codes[10:] == [429] * 4


# ------------------------------------------------------------ the limit, alone ----
def test_the_count_is_asked_of_the_first_process_when_shared(monkeypatch):
    from app.utils import rate_limit

    asked = []
    monkeypatch.setattr(rate_limit, "_shared",
                        lambda slot, limit, per, now: asked.append(slot)
                        or (True, 0))
    assert rate_limit.hit("login", "10.0.0.1", 10, 60) == (True, 0)
    assert asked == [("login", "10.0.0.1")]


def test_a_lost_count_falls_back_rather_than_locking_everyone_out(monkeypatch):
    from app.utils import rate_limit

    def gone(*_args):
        raise OSError("the first process is not answering")

    rate_limit.reset()
    monkeypatch.setattr(rate_limit, "_shared", gone)
    results = [rate_limit.hit("login", "10.0.0.2", 2, 60)[0] for _ in range(3)]
    assert results == [True, True, False]           # counted here instead
    rate_limit.reset()


# ------------------------------------------------------------ the queue ----
@pytest.fixture()
def file_db(tmp_path, monkeypatch):
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/turns.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    return app


def _together(n, work):
    gate = threading.Barrier(n)
    out = [None] * n

    def one(i):
        gate.wait()
        out[i] = work(i)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return out


def test_a_turn_is_taken_once(file_db):
    from app.extensions import db
    from app.models import Setting

    with file_db.app_context():
        Setting.set("turn", "old")
        db.session.commit()

    def take(i):
        with file_db.app_context():
            try:
                won = Setting.swap("turn", "old", f"desk{i}")
                db.session.commit()
                return won
            except Exception:                        # noqa: BLE001
                db.session.rollback()
                return False

    assert sum(_together(4, take)) == 1
    with file_db.app_context():
        assert Setting._read("turn").startswith("desk")


def test_the_first_turn_is_taken_once_too(file_db):
    from app.extensions import db
    from app.models import Setting

    def take(i):
        with file_db.app_context():
            won = Setting.swap("never-set", None, f"desk{i}")
            db.session.commit()
            return won

    assert sum(_together(4, take)) == 1


def test_the_whatsapp_queue_is_sent_by_one_of_them(file_db, monkeypatch):
    """Every screen's live refresh asks whether ten minutes have passed;
    when they have, several ask at once. One of them sends."""
    from datetime import datetime, timedelta

    from app.extensions import db
    from app.models import Setting
    from app.utils import whatsapp

    with file_db.app_context():
        Setting.set("wa_last_auto_dispatch",
                    (datetime.utcnow() - timedelta(hours=1)).isoformat())
        db.session.commit()
    sent = []
    monkeypatch.setattr(whatsapp, "dispatch_due",
                        lambda *a, **k: sent.append(1) or {"sent": 0})
    # Hold open the moment between reading the last time and writing the
    # new one, so every poll reads it before any has written — as they do
    # when a dozen screens refresh in the same second.
    real_read = Setting._read.__func__

    def slow_read(cls, key):
        value = real_read(cls, key)
        if key == "wa_last_auto_dispatch":
            time.sleep(0.3)
        return value

    monkeypatch.setattr(Setting, "_read", classmethod(slow_read))

    def poll(_i):
        with file_db.app_context():
            return whatsapp.maybe_dispatch()

    _together(4, poll)
    assert sent == [1]


# ------------------------------------------------------------ the backup ----
def test_the_nightly_backup_is_claimed_by_one(clinic, tmp_path, monkeypatch):
    from app.utils import backups

    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path))
    with clinic["app"].app_context():
        first = backups._claim("auto-backup")
        assert first is not None
        assert backups._claim("auto-backup") is None      # another process
        backups._release(first)
        again = backups._claim("auto-backup")
        assert again is not None
        backups._release(again)


def test_a_claim_left_by_a_dead_process_is_taken_over(clinic, tmp_path,
                                                      monkeypatch):
    from app.utils import backups

    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path))
    with clinic["app"].app_context():
        left = backups._claim("auto-backup")
        later = time.time() + backups._CLAIM_STALE_SECONDS + 60
        assert backups._claim("auto-backup", now=later) is not None
        assert os.path.exists(left)
        backups._release(left)


def test_while_claimed_the_others_take_no_backup(clinic, tmp_path, monkeypatch):
    from app.extensions import db
    from app.models import Setting
    from app.utils import backups

    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path))
    taken = []
    monkeypatch.setattr(backups, "create_backup",
                        lambda *a, **k: taken.append(k) or "x.db")
    monkeypatch.setattr(backups, "_retain", lambda: None)
    with clinic["app"].app_context():
        Setting.set("backup_hour", "0")
        db.session.commit()
        held = backups._claim("auto-backup")
        backups._AUTO["checked_at"] = 0.0
        assert backups.auto_backup_if_due() is None
        assert taken == []
        backups._release(held)
        backups._AUTO["checked_at"] = 0.0
        backups.auto_backup_if_due()
        assert len(taken) == 1                          # and then it is


# ------------------------------------------------------------ the update ----
def test_an_update_closes_them_all_from_the_first(monkeypatch):
    """In a worker, closing for an update asks the first process to close
    everyone — this one going alone would leave the rest serving old code
    while the files under them were replaced."""
    from app.utils import updates, workers

    asked, exited = threading.Event(), []

    class Stop:
        def set(self):
            asked.set()

    monkeypatch.setattr(workers, "_stop", Stop())
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(code))
    updates.close_after(0)
    assert asked.wait(5)
    time.sleep(0.2)
    assert exited == []


def test_alone_an_update_closes_this_process(monkeypatch):
    from app.utils import updates, workers

    exited = threading.Event()
    monkeypatch.setattr(workers, "_stop", None)
    monkeypatch.setattr(os, "_exit", lambda code: exited.set())
    updates.close_after(0)
    assert exited.wait(5)


def test_the_updater_waits_for_the_first_process(monkeypatch):
    from app.utils import updates, workers

    started = []
    monkeypatch.setenv(workers.MASTER_PID, "4242")
    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    monkeypatch.setattr(subprocess, "Popen",
                        lambda args, **k: started.append(args))
    assert updates.hand_off() is True
    assert started[0][-1] == "4242"
    monkeypatch.delenv(workers.MASTER_PID)
    assert workers.master_pid() == os.getpid()
