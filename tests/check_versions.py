"""Check that every place naming the supported Blender version agrees.

Usage (any Python 3.11+, no Blender needed):
    python tests/check_versions.py

The source of truth is instance_checker/blender_manifest.toml
(blender_version_min / blender_version_max). Supported means one minor
series, e.g. 5.3.0 <= Blender < 5.4.0, written "5.3" elsewhere. The CI download
script, the test runner's Windows default path and the docs must name the same
series. Exits non-zero and lists every mismatch.
"""

import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main():
    with open(os.path.join(ROOT, "instance_checker", "blender_manifest.toml"), "rb") as f:
        manifest = tomllib.load(f)
    vmin, vmax = manifest["blender_version_min"], manifest["blender_version_max"]
    major, minor, _patch = (int(x) for x in vmin.split("."))
    series = f"{major}.{minor}"
    problems = []
    if vmax != f"{major}.{minor + 1}.0":
        problems.append(f"manifest: blender_version_max {vmax} should be {major}.{minor + 1}.0 "
                        f"(one supported series)")

    get_blender = read(".github/scripts/get_blender.py")
    if f'VERSION = "{vmin}"' not in get_blender or f'SERIES = "{series}"' not in get_blender:
        problems.append(f".github/scripts/get_blender.py: VERSION/SERIES should be {vmin}/{series}")
    for name in re.findall(r'"(blender-[\d.]+-[a-z0-9-]+\.(?:tar\.xz|zip|dmg))"', get_blender):
        if not name.startswith(f"blender-{vmin}-"):
            problems.append(f".github/scripts/get_blender.py: {name} is not {vmin}")

    ci = read(".github/workflows/ci.yml")
    if f"blender-{vmin}-" not in ci:
        problems.append(f".github/workflows/ci.yml: cache key should name blender-{vmin}")

    expected = {  # file -> text that must appear
        "tests/run.py": f"Blender {series}\\blender.exe",
        "README.md": f"Blender {series}",
        "HANDOVER.md": f"Blender {series}",
        "AGENTS.md": f"Blender {series}",
        "CONTRIBUTING.md": f"Blender {series}",
        "SECURITY.md": f"Blender {series}",
        ".github/ISSUE_TEMPLATE/bug_report.yml": f"Blender {series} only",
    }
    for rel, text in expected.items():
        if text not in read(rel):
            problems.append(f"{rel}: should mention '{text}'")
        for other in set(re.findall(r"Blender (\d+\.\d+)\b", read(rel))) - {series}:
            problems.append(f"{rel}: mentions Blender {other}, but the supported version is {series}")

    for p in problems:
        print("MISMATCH", p)
    print(f"supported Blender {series} ({vmin} to {vmax}, exclusive): "
          f"{'all places agree' if not problems else f'{len(problems)} mismatches'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
