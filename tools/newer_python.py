"""Is there a newer Python on this computer than the one the program runs on?

Run by ``update.bat`` with the program's own Python (the one inside
``.venv``). Prints the full path of the newest Python found on this computer
that is **newer** than that one and is a version the program's libraries are
checked against (``tools/check_wheels.PYTHONS``) — or prints nothing.

Why: the program's libraries live in ``.venv``, built once from whatever
Python was installed the day the clinic was set up. Installing a newer Python
later changes nothing for the program — it keeps running on the old one,
which in time stops receiving security fixes (the About page says so). Moving
over used to be by hand: delete ``.venv``, run ``start.bat``. ``update.bat``
now does it, when it finds one — keeping the old ``.venv`` until the new one
has proved it starts.

Where it looks: the Python launcher's list (``py -0p``, which is what the
python.org installer registers), every ``python.exe`` on PATH, and the folders
the installer uses. The Microsoft Store's ``python.exe`` placeholder is not a
Python and is skipped. Each candidate is asked its own version and size; a
name is never trusted.
"""
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from check_wheels import PYTHONS  # noqa: E402

SUPPORTED = {tuple(int(p) for p in v.split(".")) for v in PYTHONS}
ASK = "import sys,struct;print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"


def _run(args, timeout=15):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def candidates(environ=None):
    """Every python executable this computer seems to have, once each."""
    environ = os.environ if environ is None else environ
    found = []
    listing = _run(["py", "-0p"])
    for line in (listing or "").splitlines():
        match = re.search(r"([A-Za-z]:\\.*?python(?:w)?\.exe|/\S*python3?(?:\.\d+)?)\s*$", line.strip())
        if match:
            found.append(match.group(1))
    for folder in (environ.get("PATH") or "").split(os.pathsep):
        for name in ("python.exe", "python3", "python"):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                found.append(path)
    for base in (environ.get("LOCALAPPDATA"), environ.get("ProgramFiles"),
                 environ.get("ProgramFiles(x86)"), environ.get("SystemDrive", "C:") + os.sep):
        if not base:
            continue
        pattern = (os.path.join(base, "Programs", "Python", "Python3*", "python.exe")
                   if base == environ.get("LOCALAPPDATA")
                   else os.path.join(base, "Python3*", "python.exe"))
        found.extend(glob.glob(pattern))
    seen, out = set(), []
    for path in found:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or "windowsapps" in key.lower():
            continue
        seen.add(key)
        out.append(path)
    return out


def describe(path):
    """``((major, minor), bits)`` — asked of the executable itself — or None."""
    reply = _run([path, "-c", ASK])
    match = re.match(r"^(\d+)\.(\d+) (32|64)\s*$", reply or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2))), int(match.group(3))


def choose(current, bits, found):
    """The newest supported one newer than ``current``; at the same version,
    the one the size of the current. ``found`` is ``[(path, (version, bits))]``."""
    better = [(v, b == bits, p) for p, (v, b) in found
              if v > current and v in SUPPORTED]
    if not better:
        return None
    return max(better, key=lambda t: (t[0], t[1]))[2]


def here():
    """This Python's own ``(version, bits)``."""
    import struct

    return tuple(sys.version_info[:2]), struct.calcsize("P") * 8


def main():
    current, bits = here()
    mine = {os.path.normcase(os.path.abspath(sys.executable))}
    found = []
    for path in candidates():
        if os.path.normcase(os.path.abspath(path)) in mine:
            continue
        info = describe(path)
        if info:
            found.append((path, info))
    choice = choose(current, bits, found)
    if choice:
        print(choice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
