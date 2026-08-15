"""Is this clinic actually ready to open? — and what is still missing.

A clinic is installed once and configured over a fortnight, in the wrong
order, by whoever is free. The pieces depend on each other and nothing says
so: you cannot set a doctor's commission before the services exist, cannot
book an appointment before somebody has working hours, cannot take money
before there is a till. So a clinic reaches its first real morning and
discovers the gap with a family standing at the desk.

**This is a checklist that inspects, not a slideshow that asks.** Every step
answers "is this done" by looking at the database, so it is right whether the
setting was made through the wizard, through the ordinary screens, or
restored from somebody else's backup. Half-configuring a clinic and coming
back tomorrow works; nothing is lost by leaving, and nothing is asked twice.

Two consequences worth stating, because they are what make it usable:

* **Order is dependency, not preference.** A step whose prerequisites are
  unmet is shown as blocked with the reason, rather than offered and then
  failing when it is opened.
* **Optional means optional.** The AI assistant and e-invoicing are real
  features and a clinic that never wants them must still be able to read
  "ready". They are listed, they are counted, and they do not gate anything.
"""


def _has(model, **filters):
    try:
        query = model.query
        if filters:
            query = query.filter_by(**filters)
        return query.first() is not None
    except Exception:                   # noqa: BLE001 - table not created yet
        return False


def _count(model, **filters):
    try:
        query = model.query
        if filters:
            query = query.filter_by(**filters)
        return query.count()
    except Exception:                   # noqa: BLE001
        return 0


# --------------------------------------------------------------- checks ----
def _identity():
    from app.models import Setting

    name = (Setting.get("clinic_name") or Setting.get("clinic_name_ar") or "").strip()
    return bool(name), name


def _timezone():
    from app.utils.clock import clinic_tz, tz_name

    return clinic_tz() is not None, tz_name()


def _facility():
    from app.utils.facility import is_configured

    try:
        return bool(is_configured()), ""
    except Exception:                   # noqa: BLE001
        return False, ""


def _doctors():
    from app.models import User

    n = _count(User, role="doctor", is_active=True)
    return n > 0, n


def _doctor_identity():
    """Every practitioner needs the things a printed prescription carries."""
    from app.models import User

    doctors = [u for u in User.query.filter_by(is_active=True).all()
               if u.role == "doctor" or u.is_practitioner]
    if not doctors:
        return False, 0
    incomplete = [d for d in doctors if not (d.signature_file and d.license_no)]
    return not incomplete, len(incomplete)


def _rooms():
    from app.models import ClinicRoom

    n = _count(ClinicRoom, is_active=True)
    return n > 0, n


def _schedules():
    from app.models import DoctorSchedule

    n = _count(DoctorSchedule)
    return n > 0, n


def _services():
    from app.models import Service

    n = _count(Service, is_active=True)
    return n > 0, n


def _commissions():
    """Priced services alone do not pay anybody — the split has to exist."""
    from app.models import Service

    try:
        priced = Service.query.filter(Service.is_active.is_(True),
                                      Service.price > 0).count()
        with_share = Service.query.filter(
            Service.is_active.is_(True),
            Service.commission_value.isnot(None),
            Service.commission_value > 0).count()
    except Exception:                   # noqa: BLE001
        return False, 0
    return (priced == 0 or with_share > 0), with_share


def _tills():
    from app.models import CashAccount

    n = _count(CashAccount)
    return n > 0, n


def _vaccines():
    from app.models import VaccineBrand

    n = _count(VaccineBrand)
    return n > 0, n


def _drugs():
    from app.models import Drug

    n = _count(Drug)
    return n > 0, n


def _icd():
    from app.utils.icd import coverage

    total = sum(v["total"] for v in coverage().values())
    return total > 0, total


def _rx_template():
    from app.models import RxPrintTemplate

    n = _count(RxPrintTemplate)
    # A clinic with none still prints correctly from the built-in default, so
    # this is a refinement rather than a blocker.
    return n > 0, n


def _backup():
    """Satisfied by a backup that exists, or by one that is scheduled.

    This used to ask one question — is the *automatic* backup switched on —
    while the sentence beside it on the checklist says a day of real data
    needs a backup behind it. So a clinic that had taken three backups by
    hand, and could see them listed on the very next screen, was still told
    the step was missing, with nothing on the page to explain why.

    Both answers are true ways to have a backup, and the count is returned so
    the checklist can say which one it found rather than only "done".
    """
    from app.models import Setting

    if (Setting.get("backup_auto") or "").strip() in ("1", "true", "on"):
        return True, ""
    try:
        from app.utils.backups import list_backups

        taken = len(list_backups())
    except Exception:            # noqa: BLE001 — a checklist never breaks a page
        return False, ""
    return taken > 0, (taken or "")


def _ai():
    from app.utils.ai import is_ready

    try:
        return is_ready(), ""
    except Exception:                   # noqa: BLE001
        return False, ""


# ---------------------------------------------------------------- steps ----
# ``needs`` lists the keys that must be done first. A step whose needs are
# unmet is shown as blocked with the reason rather than offered and then
# failing the moment it is opened.
STEPS = [
    dict(key="identity", required=True, needs=[], check=_identity,
         endpoint="settings.index"),
    dict(key="timezone", required=True, needs=[], check=_timezone,
         endpoint="settings.index"),
    # Owner-only: the facility setup reshapes what the whole institution is,
    # and a plain admin must not. The checklist used to offer the button to
    # them anyway and they met a 403 — the same failure as the two below, in
    # its third form: a button that does not take you where it says.
    dict(key="facility", required=True, needs=["identity"], check=_facility,
         endpoint="settings.setup", owner_only=True),
    dict(key="doctors", required=True, needs=["facility"], check=_doctors,
         endpoint="users.create"),
    dict(key="doctor_identity", required=False, needs=["doctors"],
         check=_doctor_identity, endpoint="users.doctors"),
    dict(key="rooms", required=False, needs=["doctors"], check=_rooms,
         endpoint="appointments.clinics"),
    dict(key="schedules", required=True, needs=["doctors"], check=_schedules,
         endpoint="appointments.schedules"),
    dict(key="services", required=True, needs=["facility"], check=_services,
         endpoint="finance.services"),
    dict(key="commissions", required=False, needs=["services", "doctors"],
         check=_commissions, endpoint="finance.services"),
    dict(key="tills", required=True, needs=["services"], check=_tills,
         endpoint="finance.tills"),
    dict(key="vaccines", required=False, needs=["facility"], check=_vaccines,
         endpoint="vaccinations.manage"),
    dict(key="drugs", required=False, needs=["facility"], check=_drugs,
         endpoint="prescriptions.drugbook"),
    dict(key="icd", required=False, needs=[], check=_icd,
         endpoint="settings.index"),
    dict(key="rx_template", required=False, needs=["doctors"],
         check=_rx_template, endpoint="prescriptions.templates"),
    # Both of these pointed somewhere that could not be opened.
    #
    # "backup" aimed at ``settings.backup_settings``, which is POST-only — it
    # *saves* the settings, it does not show them — so pressing "open" issued
    # a GET and the clinic got **405 Method Not Allowed** on the one screen
    # whose entire job is to take you somewhere.
    #
    # "ai" aimed at the settings page with no anchor, so it landed on the
    # clinic tab and left somebody hunting for the section they had just asked
    # for. The page already understands ``#ai``; the link simply never sent it.
    dict(key="backup", required=True, needs=[], check=_backup,
         endpoint="settings.data_tools", anchor="backup"),
    dict(key="ai", required=False, needs=[], check=_ai,
         endpoint="settings.index", anchor="ai"),
]


def review():
    """Every step with its state — ``done``, ``blocked`` and what it found."""
    done_keys = set()
    rows = []
    for step in STEPS:
        try:
            done, detail = step["check"]()
        except Exception:               # noqa: BLE001 - a half-built database
            done, detail = False, ""
        blocked = [k for k in step["needs"] if k not in done_keys]
        # A step whose prerequisites are unmet cannot honestly read "done",
        # even when its own check happens to pass vacuously — "doctor shares"
        # is satisfied by a clinic with no priced services, and showing that
        # as finished before services exist teaches somebody to distrust every
        # green tick on the screen.
        if blocked:
            done = False
        if done:
            done_keys.add(step["key"])
        rows.append({
            "key": step["key"], "required": step["required"],
            "endpoint": step["endpoint"], "anchor": step.get("anchor"),
            "owner_only": bool(step.get("owner_only")), "done": bool(done),
            "detail": detail, "blocked_by": blocked,
        })
    return rows


def summary():
    """Counts and the one question the banner asks: can this clinic open?"""
    rows = review()
    required = [r for r in rows if r["required"]]
    optional = [r for r in rows if not r["required"]]
    done_required = [r for r in required if r["done"]]
    return {
        "rows": rows,
        "required_total": len(required),
        "required_done": len(done_required),
        "optional_total": len(optional),
        "optional_done": len([r for r in optional if r["done"]]),
        # "Ready" is about the required steps only. A clinic that never wants
        # the AI assistant must still be able to reach the end of this.
        "ready": len(done_required) == len(required),
        "next": next((r for r in rows
                      if not r["done"] and not r["blocked_by"]), None),
    }


def dismissed():
    """Whether somebody has told the program to stop nudging about setup."""
    from app.models import Setting

    return (Setting.get("wizard_dismissed") or "") == "1"
