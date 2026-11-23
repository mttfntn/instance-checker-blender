"""Download and unpack Blender for CI, on Linux, Windows or macOS.

Usage: python .github/scripts/get_blender.py DEST_DIR

Tries download.blender.org and then official mirrors (download.blender.org
refuses some CI machines), with retries, checks the pinned SHA-256 and
unpacks into DEST_DIR. Prints the path of the Blender executable and, on
GitHub Actions, appends BLENDER=<path> to $GITHUB_ENV. If DEST_DIR already
holds an unpacked Blender (cache hit) it only prints the path.

The supported version is pinned here and in the manifest; tests/check_versions.py
checks that they agree.
"""

import hashlib
import os
import platform
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

VERSION = "5.3.0"
SERIES = "5.3"
FILES = {  # platform -> (file name, SHA-256 from blender-5.3.0.sha256)
    "Linux": ("blender-5.3.0-linux-x64.tar.xz",
              "dacb8264197a3f7fda6001285a5a506fc97ee943881261c2c3bd63c882f22e05"),
    "Windows": ("blender-5.3.0-windows-x64.zip",
                "3ac567a63d59d9934f7b9213bfb27ba05760e1fb366f8f55c381573ec3eabfa8"),
    "Darwin": ("blender-5.3.0-macos-arm64.dmg",
               "2d802b54766741e612cead50b03ebbc8eb64dadc71eda932573d256b8a784720"),
}
MIRRORS = (
    "https://download.blender.org/release",
    "https://mirrors.ocf.berkeley.edu/blender/release",
    "https://ftp.nluug.nl/pub/graphics/blender/release",
    "https://mirror.clarkson.edu/blender/release",
)


def executable(dest):
    system = platform.system()
    if system == "Darwin":
        return os.path.join(dest, "Blender.app", "Contents", "MacOS", "Blender")
    name = "blender.exe" if system == "Windows" else "blender"
    for entry in sorted(os.listdir(dest)) if os.path.isdir(dest) else ():
        path = os.path.join(dest, entry, name)
        if os.path.isfile(path):
            return path
    return os.path.join(dest, "missing", name)


def download(file_name, sha256, target):
    for base in MIRRORS:
        url = f"{base}/Blender{SERIES}/{file_name}"
        for attempt in range(1, 4):
            print(f"Trying {url} (attempt {attempt})", flush=True)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (CI build)"})
                h = hashlib.sha256()
                with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as out:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
                        out.write(chunk)
                if h.hexdigest() == sha256:
                    return
                print(f"  checksum mismatch: {h.hexdigest()}", flush=True)
                break  # a wrong file won't get better on this mirror
            except Exception as e:  # network errors: retry, then next mirror
                print(f"  failed: {e}", flush=True)
                time.sleep(10 * attempt)
    sys.exit(f"Could not download {file_name} from any mirror")


def unpack(archive, dest):
    os.makedirs(dest, exist_ok=True)
    if archive.endswith(".tar.xz"):
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")
    elif archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:  # .dmg
        mount = os.path.join(os.path.dirname(os.path.abspath(dest)), "blender_dmg")
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, archive],
                       check=True)
        try:
            subprocess.run(["cp", "-R", os.path.join(mount, "Blender.app"), dest], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", mount], check=False)


def main():
    dest = os.path.abspath(sys.argv[1])
    exe = executable(dest)
    if not os.path.isfile(exe):
        file_name, sha256 = FILES[platform.system()]
        archive = os.path.join(os.path.dirname(dest), file_name)
        download(file_name, sha256, archive)
        unpack(archive, dest)
        os.remove(archive)
        exe = executable(dest)
    if not os.path.isfile(exe):
        sys.exit(f"Blender executable not found under {dest}")
    exe = exe.replace("\\", "/")  # usable from bash on Windows too
    print(exe)
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
            f.write(f"BLENDER={exe}\n")


if __name__ == "__main__":
    main()
