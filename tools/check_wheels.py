"""Can every clinic computer install ``requirements.txt``?

The clinics run Windows, some of them 32-bit, on whatever Python was
installed the day the program was set up. ``update.bat`` installs from
ready-made wheels; a library whose version has no wheel for one of those
computers makes pip try to compile it, and the clinic's update stops there.

What this found when it was written:

* ``scipy`` (needed by ``rcpchgrowth``) has had no 32-bit Windows wheel
  since 1.9 — every 32-bit clinic's update stopped on it;
* Dependabot's first pull requests moved the 32-bit ``cryptography`` to 50
  (no 32-bit wheel) and ``uharfbuzz`` to 0.57 (no Python 3.10).

So every change to ``requirements.txt`` is resolved here for each Windows
build and Python a clinic may run, wheels only, nothing installed. ``uv``
does the resolving because it reads every marker — the clinic's own and its
libraries' — for the computer being checked, not for the one running this.

    pip install uv
    python tools/check_wheels.py              # every combination
    python tools/check_wheels.py 3.10 win32   # one
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "..", "requirements.txt")

PYTHONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
WINDOWS = {"win32": "i686-pc-windows-msvc", "win_amd64": "x86_64-pc-windows-msvc"}


def check(uv, python, platform):
    done = subprocess.run(
        [uv, "pip", "compile", REQUIREMENTS, "--quiet", "--no-header", "-o", os.devnull,
         "--python-version", python, "--python-platform", WINDOWS[platform],
         "--only-binary", ":all:"],
        capture_output=True, text=True)
    why = [line for line in (done.stderr or "").splitlines() if line.strip()]
    return done.returncode == 0, why[:4]


def main(argv):
    uv = shutil.which("uv") or os.path.join(os.path.dirname(sys.executable), "uv")
    if not os.path.exists(uv) and not shutil.which("uv"):
        print("uv is not installed: pip install uv")
        return 2
    pythons = [a for a in argv if a in PYTHONS] or list(PYTHONS)
    platforms = [a for a in argv if a in WINDOWS] or list(WINDOWS)
    failed = 0
    for platform in platforms:
        for python in pythons:
            ok, why = check(uv, python, platform)
            print(f"{'ok  ' if ok else 'FAIL'} Python {python} on {platform}")
            if not ok:
                failed += 1
                for line in why:
                    print("     " + line)
    if failed:
        print("\nA clinic on these computers could not install requirements.txt "
              "from wheels — its update.bat would stop.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
