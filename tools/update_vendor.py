"""Fetch the browser libraries in ``app/static/vendor`` at the versions
``app/static/vendor/package.json`` names — from the npm registry itself, the
package's own published files, never a copy of a copy.

    python tools/update_vendor.py            # fetch what package.json says
    python tools/update_vendor.py --check    # say what is behind, change nothing

To update one: change its version in package.json, run this, run the tests,
and look at the screens it draws (Alpine: every screen; Chart.js: the
dashboards; html2canvas: «save as image»; the icons: everywhere).

Each archive's SHA-512 is checked against the registry's own ``integrity``
before anything is unpacked, over TLS with verification on.
"""
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "..", "app", "static", "vendor")
REGISTRY = "https://registry.npmjs.org"

#: For each package: (path inside the archive, path under vendor/), the
#: first that exists wins for a target listed twice.
FILES = {
    "alpinejs": [("package/dist/cdn.min.js", "alpine.min.js")],
    "chart.js": [("package/dist/chart.umd.min.js", "chart.umd.min.js"),
                 ("package/dist/chart.umd.js", "chart.umd.min.js")],
    "html2canvas": [("package/dist/html2canvas.min.js", "html2canvas.min.js"),
                    ("package/LICENSE", "html2canvas.LICENSE.txt")],
    "bootstrap-icons": [("package/font/bootstrap-icons.min.css", "bootstrap-icons/bootstrap-icons.min.css"),
                        ("package/font/fonts/bootstrap-icons.woff2", "bootstrap-icons/fonts/bootstrap-icons.woff2"),
                        ("package/font/fonts/bootstrap-icons.woff", "bootstrap-icons/fonts/bootstrap-icons.woff")],
}


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:  # nosec - fixed https host
        return r.read()


def manifest():
    with open(os.path.join(VENDOR, "package.json"), encoding="utf-8") as fh:
        return json.load(fh)["dependencies"]


def latest(name):
    return json.loads(_get(f"{REGISTRY}/{name}/latest"))["version"]


def fetch(name, version):
    meta = json.loads(_get(f"{REGISTRY}/{name}/{version}"))
    data = _get(meta["dist"]["tarball"])
    algo, _, want = meta["dist"]["integrity"].partition("-")
    if algo != "sha512" or base64.b64encode(hashlib.sha512(data).digest()).decode() != want:
        raise SystemExit(f"{name}@{version}: the archive does not match the registry's integrity")
    done = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = set(tar.getnames())
        for inside, target in FILES[name]:
            if target in done or inside not in names:
                continue
            path = os.path.join(VENDOR, target)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as out:
                out.write(tar.extractfile(inside).read())
            done.add(target)
    missing = {t for _, t in FILES[name]} - done
    if missing:
        raise SystemExit(f"{name}@{version}: not in the package: {sorted(missing)}")
    return sorted(done)


def main(argv):
    wanted = manifest()
    if "--check" in argv:
        for name, version in wanted.items():
            newest = latest(name)
            mark = "" if newest == version else "  <- newer: " + newest
            print(f"{name:16} {version}{mark}")
        return 0
    for name, version in wanted.items():
        print(name, version, "->", ", ".join(fetch(name, version)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
