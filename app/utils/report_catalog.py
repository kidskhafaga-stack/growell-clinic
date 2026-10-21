"""Every report in the program, in one list (REPORTS_PLAN.md ت-١).

The reports were in two kinds of place: the reports screen, and the
departments' own boards (the laboratory's turnaround, the referrals, the
pharmacy's committee…). Somebody who wanted «the debts» had to know which
screen it lived on. This is the one list the «All reports» page searches.

**Each entry says who may open it — the same rule as its route.** A card that
leads to a refusal is a dead door, and ``tests/test_all_reports.py`` opens
every card each role is shown and fails on anything but the page itself.

A person's starred reports are kept as a setting per user
(``report_stars:<id>``), so they follow the person to any computer.
"""
from app.models import Setting

FINANCE, MEDICAL, OPERATIONS, QUALITY = "finance", "medical", "operations", "quality"
GROUPS = (FINANCE, MEDICAL, OPERATIONS, QUALITY)


def _opens(module):
    return lambda u: u.can_open(module)


def _reports_and(extra=None):
    return lambda u: u.can_open("reports") and (extra is None or extra(u))


def _consumption(u):
    return u.can_open("reports") and (u.can_open("inventory") or u.can_open("labs")
                                      or u.can_open("ai") or u.can("finance_manage"))


def _builder(u):
    from app.utils.report_builder import available

    return bool(available(u))


#: (endpoint, group, icon, title key, description key, who may open it)
CATALOG = [
    # ---- money ----
    ("reports.management_board", FINANCE, "building", "board_admin.title", "board_admin.desc",
     _reports_and(lambda u: u.can("finance_manage"))),
    ("reports.financial", FINANCE, "cash-coin", "reports.financial", "reports.financial_desc", _reports_and()),
    ("reports.income", FINANCE, "graph-up-arrow", "reports.income", "reports.income_desc", _reports_and()),
    ("reports.cost_centres", FINANCE, "diagram-3", "cost_centres.title", "cost_centres.desc", _reports_and()),
    ("reports.trial_balance", FINANCE, "list-columns-reverse", "trial.title", "trial.desc", _reports_and()),
    ("reports.balance_sheet", FINANCE, "columns-gap", "balsheet.title", "balsheet.desc", _reports_and()),
    ("reports.vat_summary", FINANCE, "percent", "vat.title", "vat.desc", _reports_and()),
    ("reports.ar_aging", FINANCE, "hourglass-split", "reports.ar_aging", "reports.ar_aging_desc", _reports_and()),
    ("reports.discounts", FINANCE, "tags", "reports.discounts", "reports.discounts_desc", _reports_and()),
    ("reports.staff", FINANCE, "people", "reports.staff", "reports.staff_desc", _reports_and()),
    ("finance.statements", FINANCE, "journal-text", "allrep.statements", "allrep.statements_d", _opens("finance")),
    # ---- medical ----
    # The builder makes the rest (REPORTS_PLAN.md ت-٢): any source the
    # person may use — money only with the finance rights.
    ("reports.builder", MEDICAL, "sliders", "allrep.builder", "allrep.builder_d", _builder),
    ("reports.medical_board", MEDICAL, "heart-pulse", "board_med.title", "board_med.desc", _reports_and()),
    ("reports.analytics", MEDICAL, "clipboard2-data", "reports.analytics", "reports.analytics_desc", _reports_and()),
    ("reports.vaccines", MEDICAL, "shield-plus", "reports.vaccines", "reports.vaccines_desc", _reports_and()),
    # patients.analytics is not listed: it sends whoever can open the reports
    # to the medical board, which is already here.
    ("visits.referrals", MEDICAL, "send", "allrep.referrals", "allrep.referrals_d", _opens("visits")),
    ("visits.device_board", MEDICAL, "activity", "allrep.studies", "allrep.studies_d", _opens("visits")),
    ("labs.turnaround", MEDICAL, "stopwatch", "allrep.lab_tat", "allrep.lab_tat_d", _opens("labs")),
    ("labs.send_register", MEDICAL, "truck", "allrep.lab_sendout", "allrep.lab_sendout_d", _opens("labs")),
    ("imaging.turnaround", MEDICAL, "stopwatch", "allrep.img_tat", "allrep.img_tat_d", _opens("imaging")),
    ("pharmacy.adr_board", MEDICAL, "exclamation-diamond", "allrep.adr", "allrep.adr_d", _opens("pharmacy")),
    ("pharmacy.dtc_board", MEDICAL, "people-fill", "allrep.dtc", "allrep.dtc_d", _opens("pharmacy")),
    ("beds.handover_report", MEDICAL, "arrow-left-right", "allrep.handover", "allrep.handover_d", _opens("beds")),
    ("observations.calls_report", MEDICAL, "telephone-outbound", "allrep.calls", "allrep.calls_d", _opens("observations")),
    ("theatres.pathology", MEDICAL, "eyedropper", "allrep.pathology", "allrep.pathology_d", _opens("theatres")),
    ("theatres.sedation_board", MEDICAL, "moon-stars", "allrep.sedation", "allrep.sedation_d", _opens("theatres")),
    # ---- the clinic running ----
    ("reports.operational", OPERATIONS, "calendar-check", "reports.operational", "reports.operational_desc", _reports_and()),
    ("reports.inventory", OPERATIONS, "box-seam", "reports.inventory", "reports.inventory_desc", _reports_and()),
    ("reports.consumption_board", OPERATIONS, "basket", "consumption.title", "consumption.desc", _consumption),
    ("messages.leads_board", OPERATIONS, "person-lines-fill", "reports.leads_card", "reports.leads_card_desc",
     _reports_and(lambda u: u.can_open("messages"))),
    ("messages.service_board", OPERATIONS, "speedometer2", "service.title", "reports.service_card_desc",
     _reports_and(lambda u: u.can_open("messages"))),
    ("patients.expiring_cards", OPERATIONS, "hourglass-split", "allrep.expiring", "allrep.expiring_d",
     _opens("patients")),
    ("messages.satisfaction", OPERATIONS, "star-half", "allrep.satisfaction", "allrep.satisfaction_d", _opens("messages")),
    ("messages.outcomes", OPERATIONS, "arrow-repeat", "allrep.outcomes", "allrep.outcomes_d", _opens("messages")),
    ("ambulance.report", OPERATIONS, "truck-front", "allrep.ambulance", "allrep.ambulance_d", _opens("ambulance")),
    # ---- quality ----
    ("reports.record_review", QUALITY, "clipboard-check", "record_review.title", "record_review.desc",
     _reports_and(lambda u: u.is_admin)),
    ("facility.index", QUALITY, "building-check", "facility.title", "facility.desc",
     _reports_and(lambda u: u.is_admin)),
    ("hand_hygiene.index", QUALITY, "droplet-half", "hh.title", "hh.desc", _reports_and()),
    ("theatres.site_marking_report", QUALITY, "geo-alt", "allrep.site_marking", "allrep.site_marking_d",
     _opens("theatres")),
]


def visible(user):
    """The entries this person may open, in the catalogue's order:
    ``[{endpoint, group, icon, title, desc}]``."""
    out = []
    for ep, group, icon, title, desc, check in CATALOG:
        try:
            ok = bool(check(user))
        except Exception:  # noqa: BLE001 — a broken check hides one card, not the page
            ok = False
        if ok:
            out.append({"endpoint": ep, "group": group, "icon": icon, "title": title, "desc": desc})
    return out


def _key(user):
    return f"report_stars:{user.id}"


def stars(user):
    raw = Setting.get(_key(user), "") or ""
    known = {row[0] for row in CATALOG}
    return [ep for ep in raw.split(",") if ep in known]


def toggle_star(user, endpoint):
    """Star or unstar one report for this person. Unknown names are ignored.
    Returns whether it is starred now."""
    if endpoint not in {row[0] for row in CATALOG}:
        return False
    mine = stars(user)
    if endpoint in mine:
        mine.remove(endpoint)
        now = False
    else:
        mine.append(endpoint)
        now = True
    Setting.set(_key(user), ",".join(mine))
    return now


__all__ = ["CATALOG", "GROUPS", "stars", "toggle_star", "visible"]
