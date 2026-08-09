"""ICD diagnosis reference — the whole of ICD-10, Arabic-first.

**What was here before.** Eighty-three codes. All ICD-10, no ICD-11 at all,
and the module's own docstring told the doctor that anything outside the list
"can still be entered manually" — which is a polite way of saying the search
was decoration. A paediatrician looking up a fracture, a syndrome, or half of
gastroenterology found nothing and typed free text, and a file full of free
text is a file nothing can ever report on.

**What is here now.** Two layers, and the order between them is the whole
design:

1. **The curated set** — the diagnoses this clinic actually writes, with
   Arabic titles. Small, hand-checked, and always ranked first, because a
   paediatrician typing "حرارة" wants R50.9 in the first row, not the
   twenty-third behind a list of tropical fevers.
2. **The complete ICD-10** — 71,704 codes, shipped compressed (about half a
   megabyte) and loaded only when somebody's search reaches past the curated
   list. English only, because that is how the classification is published.

So the common case stays fast and Arabic, and the long tail stops being a
dead end.

**ICD-11.** Nothing of it is bundled — not one code — and that is not an
oversight. WHO publishes ICD-11 through an API that requires the clinic to
register its own credentials; there is no public file to ship. Shipping a
partial list labelled "ICD-11" would be worse than shipping none: a doctor
would search, find nothing, and conclude the code does not exist rather than
that it was never loaded.

That failure had happened anyway, by a different route. This module said
"importable" and what existed was only :func:`install_full` — the *storage*
half — with nothing calling it, while the visit screen offered ICD-11 in its
picker regardless. So the option was there, the data never was, and the doctor
met the empty search this paragraph exists to prevent. The importer now exists
(:mod:`app.utils.icd_who`), and :func:`available_versions` is what the picker
asks, so the option and the data arrive together.
"""
import gzip
import json
import os

_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
_CURATED_PATH = os.path.join(_DIR, "icd_codes.json")
_FULL = {"10": os.path.join(_DIR, "icd10_full.json.gz"),
         "11": os.path.join(_DIR, "icd11_full.json.gz")}

DEFAULT_VERSION = "10"
VERSIONS = ["10", "11"]

_curated = None
_full_cache = {}


def _load_curated():
    """The hand-checked, Arabic-carrying list."""
    global _curated
    if _curated is None:
        with open(_CURATED_PATH, encoding="utf-8") as fh:
            rows = json.load(fh).get("codes", [])
        for row in rows:
            row.setdefault("version", DEFAULT_VERSION)
        _curated = rows
    return _curated


def _load_full(version):
    """The complete classification for one version, or ``[]`` if not loaded.

    Read once and kept, because the file is a fifth of a second to decompress
    and a doctor types four characters a second.
    """
    if version in _full_cache:
        return _full_cache[version]
    path = _FULL.get(version)
    rows = []
    if path and os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            # Stored as ``[[code, title], …]`` rather than objects: the same
            # data as dicts is six megabytes of repeated key names.
            rows = [{"code": code, "en": title, "ar": "", "version": version}
                    for code, title in json.load(fh)]
    _full_cache[version] = rows
    return rows


def coverage():
    """What is actually loaded, per version — for a screen to state plainly.

    A doctor who searches and finds nothing needs to know whether the code is
    missing from medicine or merely missing from this machine.
    """
    out = {}
    for version in VERSIONS:
        curated = sum(1 for r in _load_curated() if r["version"] == version)
        out[version] = {"curated": curated, "full": len(_load_full(version))}
        out[version]["total"] = out[version]["curated"] + out[version]["full"]
    return out


def available_versions():
    """The versions a doctor can actually be offered, because they have codes.

    ``VERSIONS`` is what the program understands; this is what it currently
    holds. The two were being conflated, and the visit screen offered
    ``ICD-11`` from a list of zero codes — so a doctor picked it, searched,
    found nothing, and concluded the diagnosis was missing from medicine
    rather than from this machine. An option that cannot deliver is worse than
    an absent one, because the person spends time on it first.

    ICD-11 appears here the moment it is imported, with no further change: the
    same function drives the picker, so the option arrives with the data.
    """
    counts = coverage()
    return [v for v in VERSIONS if counts[v]["total"] > 0]


def _rank(entry, query):
    """Lower is better, or None when this entry does not match at all."""
    code = entry["code"].lower()
    en = (entry.get("en") or "").lower()
    ar = entry.get("ar") or ""
    if code.startswith(query):
        return 0
    if en.startswith(query) or ar.startswith(query):
        return 1
    if query in code or query in en or query in ar:
        return 2
    return None


def search_icd(query, limit=15, version=None):
    """Search by code, English title, or Arabic title.

    The curated entries come first at equal rank, so the diagnoses a clinic
    writes every day keep their place at the top of the list however large the
    full classification behind them grows.
    """
    query = (query or "").strip().lower()
    wanted = version if version in VERSIONS else None

    def _pick(rows):
        return [r for r in rows if not wanted or r["version"] == wanted]

    curated = _pick(_load_curated())
    if not query:
        return curated[:limit]

    scored = []
    for entry in curated:
        rank = _rank(entry, query)
        if rank is not None:
            scored.append((rank, 0, entry))

    # Only reach for the big list when the curated one has not filled the
    # screen — which is most searches, and they never pay for it.
    if len(scored) < limit:
        seen = {e["code"].upper() for _, _, e in scored}
        for ver in ([wanted] if wanted else VERSIONS):
            for entry in _load_full(ver):
                if entry["code"].upper() in seen:
                    continue
                rank = _rank(entry, query)
                if rank is not None:
                    scored.append((rank, 1, entry))
                    if len(scored) >= limit * 4:
                        break

    scored.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in scored[:limit]]


def lookup_icd(code, version=None):
    """Return an entry by exact code, from either layer, or None."""
    code = (code or "").strip().upper()
    if not code:
        return None
    for entry in _load_curated():
        if entry["code"].upper() == code and (not version
                                              or entry["version"] == version):
            return entry
    for ver in ([version] if version in VERSIONS else VERSIONS):
        for entry in _load_full(ver):
            if entry["code"].upper() == code:
                return entry
    return None


def install_full(version, pairs):
    """Store a complete classification for ``version`` — used by the importer.

    ``pairs`` is ``[(code, title), …]``. Written compressed, in the same shape
    the bundled ICD-10 uses, so an imported ICD-11 behaves exactly like the
    ICD-10 that shipped with the program rather than being a second-class
    citizen with its own code path.
    """
    if version not in VERSIONS:
        raise ValueError(f"unknown ICD version: {version}")
    rows = [[str(code).strip().upper(), str(title).strip()]
            for code, title in pairs if str(code).strip()]
    # ``mtime=0`` so the same input produces the same bytes. Gzip stamps the
    # current time into its header by default, which would make an imported
    # file look modified after every write even when nothing in it changed —
    # noise in a clinic's backup diff, and a permanently dirty tree here.
    with open(_FULL[version], "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(rows, ensure_ascii=False,
                                separators=(",", ":")).encode("utf-8"))
    _full_cache.pop(version, None)
    return len(rows)
