"""Put the FHIR packages HL7's validator needs into ~/.fhir/packages.

The validator fetches them from packages.fhir.org. Where that host is not
reachable, the same packages are published on the npm registry, and this
copies them into the validator's cache so it runs with no network at all.

Two things are not on npm at the exact versions IPS 2.0.0 names, and are
filled with the nearest published release (the IPS package itself already
refers to extensions ``5.3.0-ballot-tc1``):

* hl7.terminology.r4 6.5.0 / 6.2.0      <- 7.0.1
* hl7.fhir.uv.extensions.r4 5.2.0        <- 5.3.0-ballot-tc1
* hl7.fhir.uv.smart-app-launch 2.0.0     <- 2.2.0

Standing in for another version creates a dependency cycle the real releases
do not have (terminology <-> extensions), which sends the validator round in
circles until it runs out of memory; the stand-ins are given R4 core as
their only dependency.

R4 core itself is ``@hl7/hl7.fhir.r4.core`` on npm (the unscoped name holds a
placeholder).

    python tools/fhir_validate/fetch_packages.py
"""
import io
import json
import os
import shutil
import tarfile
import urllib.request

REGISTRY = "https://registry.npmjs.org/"
CACHE = os.path.expanduser("~/.fhir/packages")

# (npm name, npm version, package id, versions to install it as, strip deps)
PACKAGES = (
    ("@hl7/hl7.fhir.r4.core", "4.0.1", "hl7.fhir.r4.core", ["4.0.1"], False),
    ("hl7.fhir.uv.ips", "2.0.0", "hl7.fhir.uv.ips", ["2.0.0"], False),
    ("hl7.fhir.uv.ipa", "1.1.0", "hl7.fhir.uv.ipa", ["1.1.0"], False),
    ("hl7.terminology.r4", "7.0.1", "hl7.terminology.r4",
     ["7.0.1", "6.5.0", "6.2.0"], True),
    ("hl7.fhir.uv.extensions.r4", "5.3.0-ballot-tc1",
     "hl7.fhir.uv.extensions.r4", ["5.3.0-ballot-tc1", "5.2.0"], False),
    ("hl7.fhir.uv.smart-app-launch", "2.2.0", "hl7.fhir.uv.smart-app-launch",
     ["2.2.0", "2.0.0"], True),
    ("hl7.fhir.xver-extensions", "0.1.0", "hl7.fhir.xver-extensions",
     ["0.1.0"], False),
)


def _tarball(name, version):
    meta = json.load(urllib.request.urlopen(REGISTRY + name.replace("/", "%2f")))
    return urllib.request.urlopen(meta["versions"][version]["dist"]["tarball"]).read()


def main():
    os.makedirs(CACHE, exist_ok=True)
    for npm_name, version, package_id, install_as, strip in PACKAGES:
        data = _tarball(npm_name, version)
        for as_version in install_as:
            dest = os.path.join(CACHE, f"{package_id}#{as_version}")
            if os.path.exists(dest):
                shutil.rmtree(dest)
            tarfile.open(fileobj=io.BytesIO(data)).extractall(dest)
            if strip:
                path = os.path.join(dest, "package", "package.json")
                manifest = json.load(open(path))
                manifest["dependencies"] = {"hl7.fhir.r4.core": "4.0.1"}
                json.dump(manifest, open(path, "w"), indent=2)
            print(f"{package_id}#{as_version} <- {npm_name} {version}")


if __name__ == "__main__":
    main()
