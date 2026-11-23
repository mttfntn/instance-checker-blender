"""Build the installable extension zip: dist/instance_checker-<version>.zip

Usage (repo root, any Python 3.9+):
    python tools/build.py [--blender PATH] [--check]

1. Copies instance_checker/ plus the repo LICENSE into a temporary stage
   folder, without caches.
2. Makes the stage reproducible: text files get LF line endings (so a Windows
   checkout with CRLF gives the same contents) and every file gets the same
   fixed modification time.
3. Runs Blender's own `extension validate` and `extension build`, then
   validates the zip, with --factory-startup and a scratch user profile, so
   your Blender settings are never read or changed.
4. Prints the zip path and a content digest: SHA-256 over the sorted file
   names and their uncompressed bytes. The zip's own hash can change with the
   compression library; the digest only changes when the contents do.

--check also builds from a copy of the sources with CRLF line endings and
other file times, and fails if its content digest differs.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "instance_checker"
FIXED_TIME = 1767225600  # 2026-01-01 00:00:00 UTC
TEXT_NAMES = (".py", ".toml", ".txt", ".md", ".json", "LICENSE")

sys.path.insert(0, os.path.join(ROOT, "tests"))
from run import find_blender, isolated_env  # noqa: E402


def copy_sources(src_root, dest, crlf=False, mtime=FIXED_TIME):
    """Copy src_root/PKG plus src_root/LICENSE to dest/PKG.

    Text files get LF endings (CRLF if crlf=True, to simulate a Windows
    checkout) and every file gets the modification time mtime.
    """
    target = os.path.join(dest, PKG)
    shutil.copytree(os.path.join(src_root, PKG), target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*"))
    if not os.path.exists(os.path.join(target, "LICENSE")):
        shutil.copy(os.path.join(src_root, "LICENSE"), os.path.join(target, "LICENSE"))
    for folder, _dirs, files in os.walk(target):
        for name in files:
            path = os.path.join(folder, name)
            if name.endswith(TEXT_NAMES):
                with open(path, "rb") as f:
                    data = f.read().replace(b"\r\n", b"\n")
                with open(path, "wb") as f:
                    f.write(data.replace(b"\n", b"\r\n") if crlf else data)
            os.utime(path, (mtime, mtime))
    return target


def content_digest(zip_path):
    """SHA-256 of the sorted file names and uncompressed contents of a zip."""
    h = hashlib.sha256()
    with zipfile.ZipFile(zip_path) as z:
        for name in sorted(z.namelist()):
            h.update(name.encode("utf-8") + b"\0" + z.read(name) + b"\0")
    return h.hexdigest()


def build(blender, src_root, out_dir):
    """Stage src_root's package reproducibly, validate it, build and validate the zip."""
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ic_build_") as tmp:
        stage = copy_sources(src_root, os.path.join(tmp, "stage"))
        env = isolated_env(os.path.join(tmp, "profile"))
        cmd = [blender, "--factory-startup", "--command", "extension"]
        before = set(os.listdir(out_dir))
        subprocess.run(cmd + ["validate", stage], check=True, env=env)
        subprocess.run(cmd + ["build", "--source-dir", stage, "--output-dir", out_dir],
                       check=True, env=env)
        built = sorted(set(os.listdir(out_dir)) - before) or sorted(
            f for f in os.listdir(out_dir) if f.endswith(".zip"))
        zip_path = os.path.join(out_dir, built[-1])
        subprocess.run(cmd + ["validate", zip_path], check=True, env=env)
    return zip_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=None)
    ap.add_argument("--output-dir", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--check", action="store_true",
                    help="also build from CRLF sources with other file times and compare")
    args = ap.parse_args()
    blender = find_blender(args.blender)

    zip_path = build(blender, ROOT, os.path.abspath(args.output_dir))
    digest = content_digest(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(z.namelist())
    with open(zip_path, "rb") as f:
        zip_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"built:          {zip_path}")
    print(f"files:          {', '.join(names)}")
    print(f"content digest: {digest}")
    print(f"zip sha256:     {zip_hash}")

    if args.check:
        with tempfile.TemporaryDirectory(prefix="ic_check_") as tmp:
            src = os.path.join(tmp, "src")
            copy_sources(ROOT, src, crlf=True, mtime=FIXED_TIME + 123456)
            other = content_digest(build(blender, src, os.path.join(tmp, "dist")))
        print(f"CRLF build:     {other}")
        if other != digest:
            sys.exit("NOT REPRODUCIBLE: a CRLF checkout with other file times builds different contents")
        print("reproducible:   yes")


if __name__ == "__main__":
    main()
