"""ICD diagnosis reference: in-memory search over a bundled ICD-10 set.

The runtime app is self-contained (no external ICD service dependency). The
bundled list covers common pediatric diagnoses in English and Arabic; ICD-11
or any code outside the list can still be entered manually via the diagnosis
form's version selector.
"""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "icd_codes.json")
_codes = None


def _load():
    global _codes
    if _codes is None:
        with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
            _codes = json.load(fh).get("codes", [])
    return _codes


def search_icd(query, limit=15):
    """Search bundled ICD-10 codes by code, English, or Arabic title."""
    query = (query or "").strip().lower()
    codes = _load()
    if not query:
        return codes[:limit]

    scored = []
    for entry in codes:
        code = entry["code"].lower()
        en = entry["en"].lower()
        ar = entry["ar"]
        if code.startswith(query):
            rank = 0
        elif en.startswith(query) or ar.startswith(query):
            rank = 1
        elif query in code or query in en or query in ar:
            rank = 2
        else:
            continue
        scored.append((rank, entry))

    scored.sort(key=lambda r: r[0])
    return [e for _, e in scored[:limit]]


def lookup_icd(code):
    """Return a bundled entry by exact code, or None."""
    code = (code or "").strip().upper()
    for entry in _load():
        if entry["code"].upper() == code:
            return entry
    return None
