"""Launch Blender headless in an isolated scratch profile and run a script in it.

Usage:
    python tests/run.py [--blender PATH] [--addon PATH] [--script FILE] [-- extra args]

--addon   folder of the add-on package to test (default: ./instance_checker).
          The script reads it from IC_ADDON_PATH.
--script  script to run inside Blender (default: tests/test_instance_checker.py).

Blender is started with --factory-startup, every BLENDER_USER_* path and HOME
point at a temporary folder, so your real preferences, add-ons and open Blender
sessions are never read or changed. The exit code is Blender's (non-zero if the
script fails).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_PATHS = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
)


def find_blender(explicit=None):
    """Return a Blender executable: --blender, $BLENDER, PATH or a default install."""
    for cand in (explicit, os.environ.get("BLENDER"), shutil.which("blender"), *DEFAULT_PATHS):
        if cand and os.path.isfile(cand):
            return cand
    sys.exit("Blender not found: pass --blender PATH or set $BLENDER")


def isolated_env(profile):
    """Environment that points Blender's user folders and HOME at `profile`."""
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = profile
    for sub in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
        env[f"BLENDER_USER_{sub}"] = os.path.join(profile, sub.lower())
    env["HOME"] = os.path.join(profile, "home")
    os.makedirs(env["HOME"], exist_ok=True)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=None)
    ap.add_argument("--addon", default=os.path.join(ROOT, "instance_checker"))
    ap.add_argument("--script", default=os.path.join(HERE, "test_instance_checker.py"))
    args, extra = ap.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]

    blender = find_blender(args.blender)
    profile = tempfile.mkdtemp(prefix="ic_blender_profile_")
    env = isolated_env(profile)
    env["IC_ADDON_PATH"] = os.path.abspath(args.addon)
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.abspath(args.script), "--", *extra]
    try:
        return subprocess.call(cmd, env=env)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
