"""Every role against every route, and the list of what anyone can reach.

Written after a day in which the same bug appeared four times: a permission
that the screen and the route disagreed about. A checkbox the sidebar
honoured and the route refused; three buttons drawn for the whole finance
module while their routes accept the till capability alone. None of those
fail — they look exactly like nothing being wrong — and every one was found
by somebody trying to use the feature.

So this asks the application directly, on every route, for every role,
instead of waiting for somebody to notice.

**Bogus ids on purpose.** The permission decorators run before anything loads
a row, so a role that may not reach a module must be refused even for an id
that cannot exist. A 404 where a 403 belongs is precisely the leak: it means
the row was looked for before the permission was checked.

**The public list is the important half.** Six GET routes and one POST answer
with no session at all, and each one is deliberate — a QR the pharmacy scans,
the copy a parent opens from WhatsApp, the rating link, the health check, the
login page. Pinning that set means a new public route has to be a decision
somebody makes on purpose, rather than a decorator somebody forgot.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# An id nothing can own, so a route that answers is answering about
# permission rather than about data.
BOGUS = 999999

# Everything reachable with no session at all. Each of these is deliberate:
#
#   /login                              the way in
#   /healthz                            the watchdog's check
#   /f/<token>                          the rating link sent to a family
#   /prescriptions/copy/<token>         the copy a parent opens from WhatsApp
#   /prescriptions/<id>/verify.svg      the QR a pharmacy scans
#   /vaccinations/verify/<token>        the certificate check behind a QR
#
# The WhatsApp webhooks are **not** here: they take POSTs from outside with no
# session, and refuse everything that arrives without a valid signature, so
# they never answer this sweep. That is the behaviour `test_webhook_auth`
# owns; if one ever shows up in this list, its signature check has gone.
PUBLIC = {
    ("GET", "/login"),
    ("GET", "/healthz"),
    ("GET", "/f/<token>"),
    ("POST", "/f/<token>"),
    ("GET", "/prescriptions/copy/<token>"),
    ("GET", "/prescriptions/<int:rx_id>/verify.svg"),
    ("GET", "/vaccinations/verify/<token>"),
}

# The one place a capability stands in for a whole module: reception collects
# money without being handed the ledger. Asserted to still be the only one by
# `test_the_substitution_is_still_the_only_one`, so this cannot go stale
# quietly the way a hand-kept list usually does.
CAPABILITY_FOR_MODULE = {"finance": "cashier"}


def _fill(rule):
    """A concrete URL for a rule, with ids that cannot exist."""
    url = rule.rule
    for name, converter in rule._converters.items():
        kind = type(converter).__name__
        if kind == "IntegerConverter":
            value = str(BOGUS)
        elif kind == "FloatConverter":
            value = "1.0"
        elif kind == "PathConverter":
            value = "nothing/here"
        else:
            value = "nothing"
        for prefix in ("", "int:", "float:", "path:", "string:"):
            url = url.replace(f"<{prefix}{name}>", value)
    return url


def _refused(code):
    """403 is the refusal; a redirect is the login wall. Both are fine."""
    return code in (301, 302, 401, 403)


def _reached(call, url):
    """True if the view function ran, whatever it then did.

    The distinction this file rests on. A guard is a decorator, so it answers
    *before* the view: a refusal means the view never ran, and anything else —
    a page, a 404 for a row that is not there, or a crash — means it did.

    Crashes matter more than they look. An unguarded route almost always
    raises for an anonymous caller, because the page shell asks
    ``current_user.can_access`` and there is no user to ask. The first version
    of this file caught the exception and moved on, reasoning that a 500 is
    not "public" — which quietly excused the single most likely symptom of the
    bug being hunted. Measured: strip the decorator off ``/reports/income``
    and the anonymous sweep saw nothing at all.
    """
    try:
        return not _refused(call(url, follow_redirects=False).status_code)
    except Exception:       # noqa: BLE001 - it crashed *inside* the view
        return True


@pytest.fixture()
def everyone(clinic):
    """One user per built-in role, and the roles seeded as they ship."""
    from app.extensions import db
    from app.models import Setting, User
    from app.models.permissions import MODULES, ROLES

    from app.cli import _ensure_default_roles

    with clinic["app"].app_context():
        for module in MODULES:
            Setting.set(f"module_{module}", "1")
        _ensure_default_roles()
        for role in ROLES:
            if User.query.filter_by(username=f"sweep_{role}").first():
                continue
            user = User(username=f"sweep_{role}", full_name=role, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
        db.session.commit()
    return clinic


def _as(everyone, role):
    client = everyone["app"].test_client()
    client.post("/login", data={"username": f"sweep_{role}",
                                "password": "secret"}, follow_redirects=True)
    return client


# ------------------------------------------------------- the public surface

def test_the_public_surface_is_exactly_what_we_meant(everyone):
    """What anyone on the clinic's network can reach without logging in.

    The most valuable assertion in this file. A route that loses its decorator
    does not fail anything, does not log anything, and does not look wrong —
    it just quietly joins this list.
    """
    app = everyone["app"]
    client = app.test_client()          # never logs in

    found = set()
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            for method in ("GET", "POST"):
                if method not in rule.methods:
                    continue
                call = client.get if method == "GET" else client.post
                if _reached(call, _fill(rule)):
                    found.add((method, rule.rule))

    assert found == PUBLIC, (
        "the set of routes reachable with no session has changed.\n"
        f"  newly public: {sorted(found - PUBLIC)}\n"
        f"  no longer public: {sorted(PUBLIC - found)}")


def test_the_webhooks_refuse_an_unsigned_caller(everyone):
    """They take POSTs from outside with no session, so their signature check
    is the only thing between the internet and the message log."""
    client = everyone["app"].test_client()

    for url in ("/wa/webhook/meta", "/wa/webhook/wapilot/nothing"):
        answer = client.post(url, json={"hello": "world"})
        assert _refused(answer.status_code) or answer.status_code >= 400, \
            f"{url} accepted an unsigned POST"


# --------------------------------------------------------- role vs. module

def _sweep(everyone, role):
    """Every GET route in a module blueprint, and what this role gets."""
    from app.models import Role
    from app.models.permissions import MODULES

    app = everyone["app"]
    with app.app_context():
        record = Role.query.filter_by(name=role).first()
        mine = set(record.module_list)
        is_admin = record.is_admin
        caps = {c for c in record.capability_list}

    client = _as(everyone, role)
    answered = []
    checked = 0
    with app.app_context():
        for rule in app.url_map.iter_rules():
            module = rule.endpoint.split(".")[0]
            if module not in MODULES or "GET" not in rule.methods:
                continue
            if ("GET", rule.rule) in PUBLIC:
                continue            # deliberately open to everybody
            may = is_admin or module in mine
            substitute = CAPABILITY_FOR_MODULE.get(module)
            if substitute and (substitute in caps or role == "admin"):
                may = True
            if may:
                continue
            checked += 1
            if _reached(client.get, _fill(rule)):
                answered.append((module, rule.rule))
    return checked, answered


@pytest.mark.parametrize("role", ["doctor", "reception", "accountant",
                                  "pharmacy", "nursing"])
def test_a_role_is_refused_everywhere_in_a_module_it_does_not_have(everyone, role):
    """The sweep. One line per role, and the failure names the route.

    `admin` is not swept because it reaches everything by definition; the
    thing worth checking about admin is that nobody else is one, which the
    role tests own.
    """
    checked, answered = _sweep(everyone, role)

    assert checked > 20, \
        f"only {checked} routes were checked for {role} — the sweep found nothing"
    assert not answered, (
        f"{role} was answered by {len(answered)} routes in modules it does not "
        f"have: {answered[:8]}")


def test_the_sweep_would_notice(everyone):
    """A sweep that cannot fail is not a sweep.

    Reception genuinely may reach the finance routes through the till
    capability. Take the substitution away and those routes must light up —
    which proves the sweep is looking at them rather than skipping them.
    """
    global CAPABILITY_FOR_MODULE
    original = dict(CAPABILITY_FOR_MODULE)
    CAPABILITY_FOR_MODULE = {}
    try:
        _checked, answered = _sweep(everyone, "reception")
    finally:
        CAPABILITY_FOR_MODULE = original

    assert answered, \
        "with the substitution removed the finance routes still looked refused"
    assert all(module == "finance" for module, _rule in answered), \
        f"something other than the till surface answered reception: {answered[:5]}"


# ------------------------------------------- the substitution cannot go stale

def test_the_substitution_is_still_the_only_one(everyone):
    """`CAPABILITY_FOR_MODULE` is hand-kept, so it is checked against the code.

    Exactly one decorator lets a capability stand in for a module. If a second
    one is written, this list stops describing the application and the sweep
    starts reporting a leak that is really a design decision — or worse, stops
    reporting a real one.
    """
    with open(os.path.join(ROOT, "app/utils/decorators.py"), encoding="utf-8") as fh:
        source = fh.read()

    substitutes = re.findall(r"can_access\(\"(\w+)\"\)\s*or\s*current_user\.can\(\"(\w+)\"\)",
                             source)

    assert dict(substitutes) == CAPABILITY_FOR_MODULE, (
        "the decorators substitute capabilities for modules differently than "
        f"this file expects: code says {dict(substitutes)}, "
        f"the sweep assumes {CAPABILITY_FOR_MODULE}")


def test_every_module_blueprint_was_actually_visited(everyone):
    """A scanner that silently matched nothing passes forever."""
    from app.models.permissions import MODULES

    app = everyone["app"]
    with app.app_context():
        seen = {r.endpoint.split(".")[0] for r in app.url_map.iter_rules()}

    covered = seen & set(MODULES)
    assert len(covered) >= 12, \
        f"only {len(covered)} module blueprints exist — the mapping broke"
