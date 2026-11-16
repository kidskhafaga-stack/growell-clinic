# Working on PediaPro / GROWELL CLINIC

## The plans — start here

* **`MASTER_PLAN.md`** is the one list of what is done and what is left, across
  every plan file. Read it before choosing work; the detailed plan files
  (`*_PLAN.md`) say how.
* **A part is marked done only after it is pushed and tested:** its PR is
  open, CI is green, and it was tried (tests, plus a screenshot when there is
  a screen). Mark it «✅ اتعمل (PR #n)» in `MASTER_PLAN.md` **and** in its own
  plan.
* While the PR number is not known yet, write «PR الجاي», and put the number
  in as soon as the PR is opened — `tests/test_the_master_plan_is_kept.py`
  fails CI while any plan still says it, while a «✅ اتعمل» in the master plan
  has no PR number, and while a `*_PLAN.md` file is missing from the master
  plan.
* Before writing «مش موجود» or «لسه» about anything, search the code properly
  (not `grep | head`): several plans said «لسه» about things built months
  earlier.

## Standing rules from the clinic's owner

* Discussion with the owner is in Egyptian Arabic.
* The licence private key and the signing tool never enter the repository —
  not once, not temporarily.
* TLS verification stays on.
* The AI suggests and a person confirms; it never confirms a payment from a
  screenshot, and it never invents clinical numbers.
* Every new screen has a door (a link to it), a line in the user guide
  (`app/utils/handbook.py`) and tests.
* A clinic that runs the program at clinic level only must not see hospital
  screens: hospital parts are tied to their modules (`utils/facility.py`).
* Do not change the clinic module's behaviour after an update without being
  asked.
