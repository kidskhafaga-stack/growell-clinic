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

## Keeping the libraries current

Asked for as «نتأكد انها بتتحدث لوحدها علشان الامن». What the program runs on,
and what keeps each part current:

| Part | Where | Kept current by |
|---|---|---|
| Python libraries | `requirements.txt` (exact versions) | Dependabot opens a pull request weekly, grouped (`.github/dependabot.yml`); a security fix opens one at once |
| Known vulnerabilities in them | — | `pip-audit` on every pull request (it fails the change), and weekly on its own (`.github/workflows/security-audit.yml`) |
| Browser libraries (Alpine, Chart.js, html2canvas, Bootstrap Icons) | copied into `app/static/vendor`, listed in its `package.json` | `npm audit` weekly; `python tools/update_vendor.py --check` says which are behind, and without `--check` fetches the listed versions from the npm registry, checked against its SHA-512 |
| The actions the tests run on | `.github/workflows/*.yml` | Dependabot, monthly |

A **major** version gets its own pull request and somebody reads its notes
before merging; minor and patch releases come together. Nothing reaches
`main` without the full test suite passing.

**The 32-bit Windows build** stays on `cryptography` 48.0.1: there is no
newer wheel for 32-bit, and without one the clinic's update stops. Its open
advisories concern certificate chains and PKCS#7; the licence check uses
one Ed25519 signature and neither of those. The weekly audit prints them
every week so the decision stays visible.

**A clinic** gets the new versions when it runs `update.bat` — never by
opening the program (UPGRADE_PLAN.md, step ٢).

**Python itself** is installed once on each computer and nothing updates
it. When its line stops receiving security fixes, the About page says so in
red, with what to do (`project.PYTHON_SECURITY_END`). Python 3.10 ended in
October 2026; `start.bat` now asks for 3.12 or newer.

**In the repository's settings** (Settings → Code security), *Dependabot
alerts* and *Dependabot security updates* must be on for security fixes to
open their pull request at once; the version updates above need only the
file.
