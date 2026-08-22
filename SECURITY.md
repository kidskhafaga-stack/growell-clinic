# Security Policy

## What is supported

One line, and it is `main`. There are no release branches and no version
numbers to check against: a clinic updates by taking the newest `main`, and a
fix ships there. If you are running something older, the fix for it is to
update.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting — *Security → Advisories → Report a
vulnerability* on this repository. It is visible only to the maintainer until
there is a fix.

This is maintained by one person, so an honest expectation rather than a
service level: you should hear back within a few days. If a week passes with
no reply, please assume the report was missed and open a public issue saying
only that you sent one — no details.

## Please do not send patient data

This program holds children's medical records, and the natural way to
demonstrate a bug is a screenshot of a real screen. That screenshot is the
thing this project exists to protect.

Describe the shape of the record instead — "a patient with two doses of the
same number", "a name containing a right-to-left mark" — or make one up. If a
report cannot be understood without real data, say so and it will be worked
out another way. A report with a real child's name in it will be deleted and
you will be asked to send it again.

## What is in scope

The application in this repository: its routes, its templates, its
authentication and permissions, the licence check, the update path, and
anything it writes to disk.

## What is not

* **A clinic's own installation.** How a particular practice runs Windows,
  what its network allows, whether it took the backup — those belong to that
  clinic, not to this repository.
* **The default `SECRET_KEY` in a fresh checkout.** It is replaced on first
  run with one generated for that machine and written to `clinic.env`. A
  checkout that has never been started is not a deployment.
* **The absence of a rate limit on a program that listens on a clinic's own
  network** — unless you can show it reachable from outside one.
* **Findings from an automated scanner with nothing behind them.** A report
  that says a header is missing, without saying what an attacker does with
  that, is not yet a report.

## Clinical safety is a security matter here

A wrong dose count, a schedule computed from the wrong reference, a reminder
sent to the wrong family — those are reportable through the same channel and
are taken at least as seriously as anything technical. The program refuses to
guess by design; if you find somewhere it guesses anyway, that is a bug worth
the same attention as a broken login.
