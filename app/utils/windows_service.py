"""Running the clinic as a service on a Windows server.

Asked for exactly: *keep the program running, do not let it hang, and when the
server is switched off and on again bring it back **without anybody logging
in***. Target is Windows Server 2012 R2.

**Why the Task Scheduler and not a real service.** ``sc create`` wants a binary
that speaks the Service Control Manager protocol; ``python.exe`` does not, so a
service made that way starts and is killed seconds later for "not responding".
The usual answer is a third-party wrapper (NSSM), and recommending a download
to a clinic server is a support problem for later. The Task Scheduler is *in*
Server 2012 R2, runs as ``SYSTEM`` — which needs no password, survives log-off
and starts before anyone signs in — and restarts a task that dies. It does the
job with nothing to install.

**The three settings that are the whole point**, and each has been the reason
somebody's "service" quietly stopped:

``ExecutionTimeLimit`` **PT0S** — no limit. The default is three days, after
which the Scheduler *kills the task*. A clinic server left running for a month
would go down on the fourth day, at whatever hour it had been started, for no
visible reason.

``RestartOnFailure`` — every minute, ten thousand times. A crash at 2am must
not need a person.

``StartWhenAvailable`` and the boot trigger, with the battery guards off. A
task that declines to start because a UPS reports "on battery" is one that
stays down after exactly the event it was bought for.

**And a watchdog, because "running" is not "working".** Restarting a crashed
process is the easy half. The failure a clinic actually meets is the one where
the process is alive and answering nothing — and the Scheduler cannot see that
at all, because from outside it looks identical to health. So a second task
asks ``/healthz`` on a schedule and restarts the first when it stops answering.
"""
import os

SERVICE_NAME = "GrowellClinic"
WATCHDOG_NAME = "GrowellClinicWatchdog"

# Every minute, effectively forever. The Scheduler wants a count, and a small
# one is a service that gives up on the night it was needed.
RESTART_EVERY = "PT1M"
RESTART_COUNT = 9999

# Task XML 1.2 is understood by every Windows from Vista on. 2012 R2 speaks a
# later dialect too, but nothing here needs it, and pinning the older one means
# the same file registers on a clinic's Windows 10 desktop as well.
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def task_xml(root, command, arguments="", description="", boot=True,
             every_minutes=None):
    """One Scheduled Task definition, as the XML ``schtasks /Create /XML`` takes.

    ``boot`` gives it the "at system startup" trigger — which is what makes the
    server come back on its own after a power cut. ``every_minutes`` adds a
    repeating trigger instead, for the watchdog.
    """
    triggers = []
    if boot:
        triggers.append("    <BootTrigger><Enabled>true</Enabled></BootTrigger>")
    if every_minutes:
        triggers.append(
            "    <TimeTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            "      <StartBoundary>2020-01-01T00:00:00</StartBoundary>\n"
            "      <Repetition>\n"
            f"        <Interval>PT{int(every_minutes)}M</Interval>\n"
            "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
            "      </Repetition>\n"
            "    </TimeTrigger>")

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Description>{_escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
{os.linesep.join(triggers)}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure>
      <Interval>{RESTART_EVERY}</Interval>
      <Count>{RESTART_COUNT}</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_escape(command)}</Command>
      <Arguments>{_escape(arguments)}</Arguments>
      <WorkingDirectory>{_escape(root)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def service_xml(root):
    """The task that runs the clinic."""
    return task_xml(
        root, command=os.path.join(root, "serve.bat"),
        description="GROWELL CLINIC — runs the clinic server and restarts it "
                    "if it stops. Starts at boot, before anybody signs in.",
        boot=True)


def watchdog_xml(root, every_minutes=5):
    """The task that checks the first one is *answering*, not merely alive."""
    return task_xml(
        root, command=os.path.join(root, "watchdog.bat"),
        description="GROWELL CLINIC — asks the clinic server whether it is "
                    "answering, and restarts it when it is not.",
        boot=False, every_minutes=every_minutes)


def write_definitions(root, every_minutes=5):
    """Write both task files next to the program and return their paths.

    UTF-16 with a BOM because that is what ``schtasks /Create /XML`` expects;
    handed a UTF-8 file it fails with a parse error that says nothing about
    encoding, which is a long evening for whoever is installing this.
    """
    out = {}
    for name, xml in ((SERVICE_NAME, service_xml(root)),
                      (WATCHDOG_NAME, watchdog_xml(root, every_minutes))):
        path = os.path.join(root, f"{name}.xml")
        with open(path, "w", encoding="utf-16") as fh:
            fh.write(xml)
        out[name] = path
    return out


def install_commands(root, every_minutes=5):
    """The ``schtasks`` calls that register both tasks, in order.

    Returned as a list rather than run here so the installer can print exactly
    what it is about to do to somebody's server, and so this is testable
    without a Windows machine.
    """
    files = {SERVICE_NAME: os.path.join(root, f"{SERVICE_NAME}.xml"),
             WATCHDOG_NAME: os.path.join(root, f"{WATCHDOG_NAME}.xml")}
    commands = []
    for name in (SERVICE_NAME, WATCHDOG_NAME):
        # /F replaces an existing registration: installing twice is what a
        # person does after changing the port, and it must not be an error.
        commands.append(["schtasks", "/Create", "/TN", name,
                         "/XML", files[name], "/F"])
    commands.append(["schtasks", "/Run", "/TN", SERVICE_NAME])
    return commands


def remove_commands():
    return [["schtasks", "/End", "/TN", SERVICE_NAME],
            ["schtasks", "/Delete", "/TN", SERVICE_NAME, "/F"],
            ["schtasks", "/Delete", "/TN", WATCHDOG_NAME, "/F"]]
