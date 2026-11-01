"""The browser libraries copied into ``app/static/vendor`` are the versions
``app/static/vendor/package.json`` lists — «نتأكد انها بتتحدث … علشان الامن».

The manifest is what GitHub's security alerts read and what
``tools/update_vendor.py`` fetches. A file changed without the manifest (or
the other way round) would make the alerts speak about a version the clinic
is not running; this test is what keeps the two the same.
"""
import json
import os

VENDOR = os.path.join(os.path.dirname(__file__), "..", "app", "static", "vendor")

#: How each file says which version it is.
MARKS = {
    "alpinejs": ("alpine.min.js", 'version:"{v}"'),
    "chart.js": ("chart.umd.min.js", "Chart.js v{v}"),
    "html2canvas": ("html2canvas.min.js", "html2canvas {v}"),
    "bootstrap-icons": ("bootstrap-icons/bootstrap-icons.min.css", "Bootstrap Icons v{v}"),
}


def _manifest():
    with open(os.path.join(VENDOR, "package.json"), encoding="utf-8") as fh:
        return json.load(fh)["dependencies"]


def test_every_listed_library_is_the_listed_version():
    listed = _manifest()
    assert set(listed) == set(MARKS), "a library added or removed without saying how to read it"
    for name, version in listed.items():
        path, mark = MARKS[name]
        with open(os.path.join(VENDOR, path), encoding="utf-8", errors="replace") as fh:
            head = fh.read(400_000)
        assert mark.format(v=version) in head, f"{path} is not {name} {version}"


def test_every_vendored_script_is_listed():
    """A new library dropped into vendor/ without a line in the manifest is
    one the security alerts never hear about."""
    files = {f for f in os.listdir(VENDOR) if f.endswith((".js", ".css"))}
    known = {MARKS[n][0] for n in MARKS if "/" not in MARKS[n][0]}
    assert files <= known, f"not in package.json: {sorted(files - known)}"
