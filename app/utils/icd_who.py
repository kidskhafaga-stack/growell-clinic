"""Fetching ICD-11 from WHO once, so the clinic never needs WHO again.

**Why an import and not a live search.** WHO's ICD-11 API is the only way to
get the classification — there is no file to ship, and the licence is why. But
a clinic that asks WHO on every keystroke has a diagnosis picker that stops
working when the line drops, and in an Egyptian clinic the line drops. Worse,
it drops silently: the doctor types, nothing appears, and there is no way to
tell "no such code" from "no such internet" while a parent is sitting there.

So this runs once. It walks the classification, writes it next to the bundled
ICD-10 in exactly the same format, and after that the program is offline again
and ICD-11 searches at the same speed as ICD-10.

**The credentials are the clinic's own.** WHO issues a free client id and
secret per registrant at https://icd.who.int/icdapi. They are not ours to
embed and would not survive being embedded — one key shared by every install
is one key to be rate-limited and revoked. The clinic registers, pastes two
strings into Settings once, presses import, and never thinks about it again.

**On the shape of this module.** Everything that decides *what a code is* is a
plain function over data that WHO already sent — :func:`entity_code`,
:func:`child_uris`, :func:`flatten`. Only :func:`_get` and :func:`token` touch
the network. That split is deliberate and is the reason the tests below mean
something: this was written where WHO is unreachable, so the parsing is tested
against recorded response shapes and the transport is kept too thin to hide a
bug. The clinic finds out about the transport in one second with
:func:`test_connection`, rather than after a twenty-minute import.
"""
import time

# WHO's OAuth2 token endpoint. Client-credentials grant, scope icdapi_access,
# tokens good for about an hour — which a long walk will outlive, so
# :class:`Session` refreshes rather than assuming.
TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
SCOPE = "icdapi_access"

# The classification itself. "mms" is Mortality and Morbidity Statistics — the
# main linearization, and the one a clinic means when it says ICD-11.
API_ROOT = "https://id.who.int/icd/release/11"
LINEARIZATION = "mms"

REGISTER_URL = "https://icd.who.int/icdapi"

# WHO asks for these two headers on every call: the API version and the
# language. Without them the service answers in a shape this code would not
# recognise, which is a confusing way to discover a missing header.
API_VERSION = "v2"
LANGUAGE = "en"

REQUEST_TIMEOUT = 30

# A courtesy pause between calls. The walk is thousands of requests against a
# free public service that a clinic did not pay for; hammering it is how the
# credential everybody shares gets throttled for everybody.
POLITE_DELAY = 0.05


def settings():
    """The clinic's WHO credentials and chosen release, from the settings table."""
    from app.models import Setting

    return {
        "client_id": (Setting.get("icd11_client_id") or "").strip(),
        "client_secret": (Setting.get("icd11_client_secret") or "").strip(),
        # Blank means "whatever WHO currently calls latest", which is the right
        # default: a clinic should not have to know release ids to get started.
        "release": (Setting.get("icd11_release") or "").strip(),
    }


def configured(cfg=None):
    """Whether there is anything to try with."""
    cfg = cfg or settings()
    return bool(cfg["client_id"] and cfg["client_secret"])


# ------------------------------------------------------------- parsing -----
# Nothing below this line touches the network. WHO's payloads are the input.

def _text(value):
    """WHO wraps every human-readable string as ``{"@value": "..."}``."""
    if isinstance(value, dict):
        return (value.get("@value") or "").strip()
    return (value or "").strip()


def entity_code(entity):
    """The ICD-11 code of one entity, or ``None`` when it has none.

    Most of the tree has no code. Chapters, blocks and grouping nodes exist to
    organise the classification and are not diagnoses anybody writes on a
    file — WHO simply omits ``code`` for them. Storing them would put "Certain
    infectious or parasitic diseases" in a doctor's picker as though it were
    something to diagnose a child with.
    """
    code = (entity.get("code") or "").strip()
    return code or None


def entity_title(entity):
    """The entity's title, with WHO's markup for post-coordination removed.

    Titles come back containing ``&amp;`` and occasional HTML entities because
    the browser renders them. A picker showing "Fever &amp; rash" is a picker
    that looks broken, so they are turned back into the characters they mean.
    """
    import html

    return html.unescape(_text(entity.get("title"))).strip()


def child_uris(entity):
    """The children of one entity, as absolute URIs.

    Returns ``[]`` rather than ``None`` for a leaf, so a caller can walk the
    whole tree without asking whether each node happens to have children.
    """
    return [uri for uri in (entity.get("child") or []) if uri]


def release_index(entity):
    """The linearization to walk, when what came back is a *list of releases*.

    Reported as: the connection works and the download brings nothing back.

    ``/icd/release/11/mms`` — the address used when a clinic pins no release,
    which is the default and the sensible one — does not answer with the
    classification. It answers with the releases that exist:

        {"release": [".../2024-01/mms", ".../2023-01/mms", …],
         "latestRelease": ".../2024-01/mms"}

    There is no ``child`` in that, so the walk collected exactly one entity,
    found no code on it, and stopped — in seconds, reporting "WHO returned no
    codes". True, and useless: the walk had never reached the classification.

    Returns the URI to start from instead, or None when this really is a node
    of the tree.
    """
    if entity.get("child"):
        return None
    latest = entity.get("latestRelease")
    if latest:
        return latest
    releases = entity.get("release") or []
    # Newest first is what WHO returns; taking the first is "latest" when
    # ``latestRelease`` is absent rather than guessing at version strings.
    return releases[0] if releases else None


def flatten(entities):
    """Turn walked entities into the ``(code, title)`` pairs storage wants.

    Deduplicated by code, keeping the first title seen. The classification is
    a graph rather than a tree — an entity can be reached down more than one
    branch — so without this a walk produces the same code several times and
    the picker shows the same diagnosis three rows apart.
    """
    seen, out = set(), []
    for entity in entities:
        code = entity_code(entity)
        title = entity_title(entity)
        if not code or not title or code.upper() in seen:
            continue
        seen.add(code.upper())
        out.append((code, title))
    return out


# ----------------------------------------------------------- transport -----

class Session:
    """One authenticated conversation with WHO, refreshing its own token.

    A full walk takes longer than the hour WHO's tokens last, so the token is
    re-fetched on expiry rather than obtained once and hoped over. A twenty
    minute import that dies at minute sixty-one with "401" and no explanation
    is the kind of failure a clinic gives up on rather than reports.
    """

    def __init__(self, cfg=None, requests=None):
        self.cfg = cfg or settings()
        self._requests = requests
        self._token = None
        self._expires_at = 0.0

    @property
    def requests(self):
        if self._requests is None:
            import requests as real
            self._requests = real
        return self._requests

    def token(self):
        """A valid bearer token, fetched or reused."""
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        resp = self.requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            auth=(self.cfg["client_id"], self.cfg["client_secret"]),
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise WhoError(_auth_error(resp))
        payload = resp.json()
        self._token = payload.get("access_token")
        if not self._token:
            raise WhoError("who_no_token")
        self._expires_at = time.time() + float(payload.get("expires_in") or 3600)
        return self._token

    def get(self, url):
        """One entity from WHO, as a dict."""
        resp = self.requests.get(url, timeout=REQUEST_TIMEOUT, headers={
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/json",
            "Accept-Language": LANGUAGE,
            "API-Version": API_VERSION,
        })
        if not resp.ok:
            raise WhoError(f"HTTP {resp.status_code}")
        return resp.json()


class WhoError(Exception):
    """A failure worth showing a human, phrased as a key a screen translates."""


def _auth_error(resp):
    """Name the likely cause of a rejected token request.

    "HTTP 400" tells a clinic nothing it can act on. Wrong credentials is by
    far the most common cause and is the one thing they can fix themselves.
    """
    if resp.status_code in (400, 401):
        return "who_bad_credentials"
    return f"who_auth_http_{resp.status_code}"


def test_connection(cfg=None, requests=None):
    """One token request, so the clinic learns in a second rather than an hour.

    Deliberately separate from the import: pasting a secret wrong is the
    ordinary mistake, and finding out about it twenty minutes into a walk is
    the kind of thing that makes people stop trusting a button.
    """
    cfg = cfg or settings()
    if not configured(cfg):
        return {"ok": False, "error": "who_not_configured"}
    try:
        Session(cfg, requests=requests).token()
    except WhoError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:                # noqa: BLE001 - network, DNS, TLS
        return {"ok": False, "error": f"network: {exc}"}
    return {"ok": True}


def root_url(cfg=None):
    """Where the walk starts — the pinned release, or whatever WHO calls latest."""
    cfg = cfg or settings()
    if cfg["release"]:
        return f"{API_ROOT}/{cfg['release']}/{LINEARIZATION}"
    return f"{API_ROOT}/{LINEARIZATION}"


def walk(session, start=None, on_progress=None, limit=None):
    """Every entity under the linearization root, breadth-first.

    Breadth-first rather than recursive: ICD-11 is deep, and a recursive walk
    over a classification whose depth WHO controls is a stack overflow waiting
    for a release that adds a level. The visited set is what makes it finite —
    the classification is a graph, and a node reachable by two paths would
    otherwise be walked twice and its whole subtree with it.

    ``on_progress`` is called with the running count so a screen can show that
    something is happening; this takes minutes, and a spinner with no number
    is indistinguishable from a hang.
    """
    first = start or root_url(session.cfg)
    queue = [first]
    seen_urls, entities = set(), []
    hopped = False
    while queue:
        url = queue.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        entity = session.get(url)

        # The address a clinic lands on when it pins no release answers with
        # the *list of releases*, not the classification — see
        # ``release_index``. Checked only on the very first response, and the
        # response is reused rather than re-fetched when it turns out to be a
        # real node, so the ordinary case costs nothing.
        if not hopped and not entities:
            hopped = True
            moved = release_index(entity)
            if moved:
                queue.insert(0, moved)
                continue

        entities.append(entity)
        queue.extend(uri for uri in child_uris(entity) if uri not in seen_urls)
        if on_progress:
            on_progress(len(entities))
        if limit and len(entities) >= limit:
            break
        if POLITE_DELAY:
            time.sleep(POLITE_DELAY)
    return entities


def import_all(cfg=None, requests=None, on_progress=None, limit=None):
    """Fetch ICD-11 and store it beside the bundled ICD-10.

    Returns ``{"ok", "codes"}`` or ``{"ok": False, "error"}``. Nothing is
    written unless the walk finished and produced codes: a half-written
    classification is worse than none, because the doctor gets *some* results
    and has no reason to suspect the rest is missing.
    """
    from app.utils.icd import install_full

    cfg = cfg or settings()
    if not configured(cfg):
        return {"ok": False, "error": "who_not_configured"}
    try:
        session = Session(cfg, requests=requests)
        entities = walk(session, on_progress=on_progress, limit=limit)
    except WhoError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:                # noqa: BLE001 - network, DNS, TLS
        return {"ok": False, "error": f"network: {exc}"}

    pairs = flatten(entities)
    if not pairs:
        # "WHO returned no codes" was true and undiagnosable: it says the same
        # thing whether the walk never reached the classification (one entity,
        # the release list) or reached it and found nothing coded. Those are a
        # broken start address and a broken parser, and they are fixed in
        # different files. The count separates them at a glance.
        return {"ok": False, "error": "who_empty", "walked": len(entities)}
    install_full("11", pairs)
    return {"ok": True, "codes": len(pairs)}
