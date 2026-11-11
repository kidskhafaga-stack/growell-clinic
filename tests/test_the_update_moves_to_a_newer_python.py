"""The update moves the program onto a newer Python when one is installed.

The libraries live in ``.venv``, built from whatever Python the clinic had
on day one. Installing a newer Python changed nothing for the program until
somebody deleted ``.venv`` by hand. ``update.bat`` now notices
(``tools/newer_python.py``), sets the libraries up on the newer one — only a
version they are checked against — and keeps the old ``.venv`` until the
program has started on the new one, putting it back if it does not.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools")))

import newer_python  # noqa: E402
from check_wheels import PYTHONS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _update():
    with open(os.path.join(ROOT, "update.bat"), encoding="utf-8", newline="") as fh:
        return fh.read()


def _label(text, name):
    """Where the label line ``:name`` stands — not a ``goto``/``call`` to it."""
    return re.search(rf"^:{name}\r?$", text, re.M).start()


def test_only_versions_the_libraries_are_checked_against():
    assert newer_python.SUPPORTED == {tuple(int(p) for p in v.split(".")) for v in PYTHONS}


def test_the_newest_supported_one_newer_than_now_is_chosen():
    found = [("C:\\Python311\\python.exe", ((3, 11), 64)),
             ("C:\\Python313\\python.exe", ((3, 13), 64)),
             ("C:\\Python314-32\\python.exe", ((3, 14), 32)),
             ("C:\\Python314\\python.exe", ((3, 14), 64)),
             ("C:\\Python315\\python.exe", ((3, 15), 64))]     # not checked yet
    assert newer_python.choose((3, 11), 64, found) == "C:\\Python314\\python.exe"
    # The same size as now wins a tie; a 32-bit clinic stays 32-bit.
    assert newer_python.choose((3, 11), 32, found) == "C:\\Python314-32\\python.exe"


def test_nothing_when_nothing_is_newer():
    found = [("C:\\Python310\\python.exe", ((3, 10), 64)),
             ("C:\\Python312\\python.exe", ((3, 12), 64))]
    assert newer_python.choose((3, 12), 64, found) is None
    assert newer_python.choose((3, 14), 64, []) is None


def test_the_launcher_s_list_is_read_and_the_store_placeholder_skipped(monkeypatch, tmp_path):
    listing = (" -V:3.14 *        C:\\Users\\Clinic\\AppData\\Local\\Programs\\Python\\Python314\\python.exe\n"
               " -3.12-32        C:\\Program Files (x86)\\Python312-32\\python.exe\n")
    monkeypatch.setattr(newer_python, "_run",
                        lambda args, timeout=15: listing if args[0] == "py" else None)
    store = tmp_path / "WindowsApps"
    store.mkdir()
    (store / "python.exe").write_text("")
    found = newer_python.candidates({"PATH": str(store)})
    assert "C:\\Users\\Clinic\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" in found
    assert "C:\\Program Files (x86)\\Python312-32\\python.exe" in found
    assert not [p for p in found if "WindowsApps" in p]


def test_a_python_is_asked_its_version_not_judged_by_its_name():
    version, bits = newer_python.describe(sys.executable)
    assert version == tuple(sys.version_info[:2]) and bits in (32, 64)
    assert newer_python.describe(os.path.join(ROOT, "run.py")) is None


def test_it_prints_a_newer_python_or_nothing():
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "newer_python.py")],
                         capture_output=True, text=True, timeout=120).stdout.strip()
    if out:
        version, _bits = newer_python.describe(out)
        assert version > tuple(sys.version_info[:2]) and version in newer_python.SUPPORTED


def test_the_update_asks_before_installing_the_libraries():
    text = _update()
    fetched, asks, deps = (_label(text, "fetched"), text.index("tools\\newer_python.py 2^>nul"),
                           text.index("echo [3/5] Installing dependencies..."))
    assert fetched < asks < deps


def test_the_old_libraries_are_kept_until_the_program_has_started():
    text = _update()
    switch = text[_label(text, "switch_python"):_label(text, "python_back")]
    assert 'ren ".venv" ".venv.previous"' in switch
    assert 'rmdir /s /q ".venv"' not in switch, "never delete the working .venv first"
    # Removed only after the start check and the version record.
    assert _label(text, "started") < text.index('rmdir /s /q ".venv.previous"\r\n\r\necho.')
    # A failed start on the new Python goes back and asks again.
    check = text[text.index("echo [5/5]"):_label(text, "started")]
    assert "call :python_back" in check and check.count("raise SystemExit") == 2
    # Never copied over by a downloaded update.
    assert "/XD data instance .venv .venv.previous" in text


def test_the_new_part_has_no_bracket_blocks():
    """A `)` inside a block closes it where it stands — this file has had
    that bug. The new part is labels and goto only."""
    text = _update()
    part = text[_label(text, "switch_python"):_label(text, "fetch_zip")]
    code = "\n".join(line for line in part.splitlines() if not line.startswith("REM"))
    assert not re.search(r"\(\s*$", code, re.M)
