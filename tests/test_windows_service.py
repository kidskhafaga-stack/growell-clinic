"""Running the clinic as a service on a Windows server.

Asked for exactly: keep the program running, do not let it hang, and when the
server is switched off and on again bring it back **without anybody logging
in**. Target: Windows Server 2012 R2.

These tests cannot start a Scheduled Task from Linux, and pretending otherwise
would be theatre. What they can do is pin the handful of settings that decide
whether the thing survives a month unattended — every one of which has, in
somebody's clinic, been the reason a "service" quietly stopped:

* **no execution time limit** — the Scheduler's default is three days, after
  which it *kills the task*. A server left alone goes down on the fourth day
  for no visible reason;
* **SYSTEM, at boot** — that is what "comes back without anybody logging in"
  actually means;
* **restart on failure**, many times, so a crash at 2am does not need a person;
* **the battery guards off** — a task that refuses to run because a UPS says
  "on battery" is one that stays down after exactly the event the UPS was
  bought for.

And the watchdog, which is the part that is not obvious: the Scheduler restarts
a process that *died*. The failure a clinic meets is the one where the process
is alive and answering nothing, and from outside that is indistinguishable from
health.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def xml():
    from app.utils.windows_service import service_xml

    return service_xml(r"C:\growell-clinic")


# ================================================ the settings that decide it ==
def test_the_task_has_no_execution_time_limit(xml):
    """The default is three days and then the Scheduler kills it. A clinic
    server left running would go down on the fourth day, at whatever hour it
    was started, with nothing in the log to explain it."""
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml


def test_it_runs_as_system(xml):
    """S-1-5-18. No password to store, no session to expire, and it starts
    before anybody signs in — which is the whole request."""
    assert "<UserId>S-1-5-18</UserId>" in xml


def test_it_starts_at_boot(xml):
    """"The computer was switched off and on again" has to be enough."""
    assert "<BootTrigger>" in xml


def test_it_restarts_itself_when_it_stops(xml):
    from app.utils.windows_service import RESTART_COUNT

    assert "<RestartOnFailure>" in xml
    assert "<Interval>PT1M</Interval>" in xml
    assert f"<Count>{RESTART_COUNT}</Count>" in xml
    assert RESTART_COUNT >= 1000, "a small count gives up on the night it matters"


def test_a_ups_on_battery_does_not_keep_it_down(xml):
    """The power cut is the event the UPS exists for. A task that declines to
    start while on battery is one that stays down through it."""
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml


def test_a_missed_start_is_still_a_start(xml):
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml


def test_two_copies_never_run_at_once(xml):
    """Two servers on one port is one server and one crash loop."""
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml


def test_it_does_not_wait_for_the_network(xml):
    """The clinic serves itself on localhost. Refusing to start until a switch
    finishes negotiating is a server that comes back last after a power cut."""
    assert "<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>" in xml


def test_it_is_not_an_idle_task(xml):
    """"Only when the machine is idle" on a clinic server means "not during
    clinic hours"."""
    assert "<RunOnlyIfIdle>false</RunOnlyIfIdle>" in xml


def test_the_schema_is_the_one_every_windows_understands(xml):
    """Task XML 1.2 registers on Vista onwards. 2012 R2 speaks a later dialect
    and nothing here needs it — pinning the older one means the same file
    works on a clinic's desktop as well as its server."""
    assert 'version="1.2"' in xml


# ================================================================ the watchdog ==
def test_the_watchdog_runs_on_a_repeating_schedule():
    from app.utils.windows_service import watchdog_xml

    body = watchdog_xml(r"C:\growell-clinic", every_minutes=5)
    assert "<TimeTrigger>" in body
    assert "<Interval>PT5M</Interval>" in body


def test_the_watchdog_does_not_start_at_boot():
    """It checks something that is still coming up. Its repeating trigger
    brings it round soon enough."""
    from app.utils.windows_service import watchdog_xml

    assert "<BootTrigger>" not in watchdog_xml(r"C:\x", every_minutes=5)


def test_the_two_tasks_point_at_their_own_scripts():
    from app.utils.windows_service import service_xml, watchdog_xml

    assert "serve.bat" in service_xml(r"C:\growell")
    assert "watchdog.bat" in watchdog_xml(r"C:\growell")


# ============================================================== registration ==
def test_installing_twice_replaces_rather_than_fails():
    """Changing the port and re-installing is a normal afternoon, not an
    error."""
    from app.utils.windows_service import install_commands

    for command in install_commands(r"C:\growell"):
        if "/Create" in command:
            assert "/F" in command


def test_installing_starts_it_without_a_reboot():
    from app.utils.windows_service import SERVICE_NAME, install_commands

    assert ["schtasks", "/Run", "/TN", SERVICE_NAME] in install_commands(r"C:\x")


def test_removing_stops_it_first():
    """Deleting a running task leaves the process behind, holding the port."""
    from app.utils.windows_service import remove_commands

    commands = remove_commands()
    assert commands[0][1] == "/End"
    assert any("/Delete" in c for c in commands)


def test_the_definitions_are_written_as_utf16(tmp_path):
    """``schtasks /Create /XML`` handed a UTF-8 file fails with a parse error
    that says nothing about encoding — a long evening for whoever is
    installing this."""
    from app.utils.windows_service import write_definitions

    paths = write_definitions(str(tmp_path))
    assert len(paths) == 2
    for path in paths.values():
        with open(path, "rb") as fh:
            head = fh.read(2)
        assert head in (b"\xff\xfe", b"\xfe\xff"), "not a UTF-16 BOM"


# ============================================== what the service actually runs ==
def _script(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _commands(name):
    """The script with its comments removed — what actually runs."""
    return "\n".join(line for line in _script(name).splitlines()
                     if not line.strip().lower().startswith("rem"))


def test_the_service_script_never_waits_for_a_person():
    """It runs as SYSTEM at boot with no desktop. A pause, a prompt or a
    browser window is a server that never finishes starting."""
    body = _commands("serve.bat").lower()
    assert "pause" not in body
    assert "set /p" not in body
    assert 'start "" "http' not in body


def test_the_service_script_uses_the_venv_python_by_full_path():
    """SYSTEM has a different PATH from whoever installed Python, and a
    per-user install is not on it at all."""
    body = _script("serve.bat")
    assert ".venv\\Scripts\\python.exe" in body
    assert "where python" not in body


def test_the_service_script_matches_the_database_shape_first():
    """Same rule as start.bat: reading a database whose shape does not match
    the code gives wrong numbers rather than an error."""
    body = _script("serve.bat")
    assert "sync-db" in body
    assert "SCHEMA UPGRADE FAILED" in body


def test_the_service_script_rotates_its_log():
    """A log nobody rotates is a disk that fills, and a full disk stops a
    clinic as surely as a crash."""
    assert "service.old.log" in _script("serve.bat")


def test_the_watchdog_asks_twice_before_restarting():
    """One slow answer during a backup is not a dead server, and a watchdog
    that restarts on every hiccup is worse than no watchdog."""
    body = _script("watchdog.bat")
    assert body.count("app.health_check") >= 2


def test_the_installer_refuses_without_administrator():
    """Without it the registration fails silently and nothing says why."""
    body = _script("service.bat")
    assert "net session" in body
    assert "Run this as Administrator" in body


def test_the_installer_opens_the_firewall_on_the_real_port():
    """A rule for 5000 while the clinic serves on 8080 is a morning spent on
    "the other computers cannot see it"."""
    body = _script("service.bat")
    assert "netsh advfirewall" in body
    assert "chosen_port" in body


# =================================================================== /healthz ==
def test_the_health_route_is_open(clinic):
    """A watchdog cannot sign in, and a check that needs a session reports
    "unhealthy" every time somebody's cookie expires."""
    client = clinic["app"].test_client()
    reply = client.get("/healthz")
    assert reply.status_code == 200
    assert reply.get_json()["status"] == "ok"


def test_the_health_route_touches_the_database(clinic):
    """A route that only proves Python is alive would answer happily through
    exactly the failure it exists to catch."""
    client = clinic["app"].test_client()
    assert client.get("/healthz").get_json()["database"] is True


def test_the_health_route_says_nothing_about_the_clinic(clinic):
    """It is open, so it carries a status and a version and nothing that names
    a clinic or counts its patients."""
    body = clinic["app"].test_client().get("/healthz").get_json()
    assert set(body) == {"status", "database", "version"}


def test_a_dead_clinic_is_reported_as_dead():
    """The check is its own process with its own timeout — importing the app to
    test the app would hang in the case this exists to detect."""
    from app.health_check import check

    ok, message = check(port=59999, timeout=1)
    assert ok is False and message
