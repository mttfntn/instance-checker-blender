"""Install a built zip in a scratch Blender profile and check that it works.

Usage (outside Blender):
    python tests/check_installed_package.py dist/instance_checker-<version>.zip [--blender PATH]

Installs the zip with `blender --command extension install-file --enable` into a
temporary profile (never your own), then starts Blender again in that profile
and runs this file inside it. There it checks that the extension was loaded
the way users get it (as bl_ext.user_default.instance_checker), that the
manifest version matches, that LICENSE was shipped, and that Scan, Instance
All and Make Copies work on a small scene.
"""

import os
import subprocess
import sys
import tempfile


def check_inside_blender():
    import addon_utils
    import bpy
    import tomllib

    fails = []

    def check(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    mod_name = "bl_ext.user_default.instance_checker"
    enabled = {m.module for m in bpy.context.preferences.addons}
    check(mod_name in enabled, f"{mod_name} is enabled")
    mod = sys.modules.get(mod_name)
    check(mod is not None, "module imported")
    folder = os.path.dirname(mod.__file__)
    check(os.path.isfile(os.path.join(folder, "LICENSE")), "LICENSE shipped")
    shipped = sorted(f for f in os.listdir(folder) if not f.startswith("__pycache__"))
    print("  files:", ", ".join(shipped))
    with open(os.path.join(folder, "blender_manifest.toml"), "rb") as f:
        version = tomllib.load(f)["version"]
    info = addon_utils.module_bl_info(mod)
    check(".".join(map(str, info["version"])) == version, f"loaded version {version}")

    # Empty the scene by hand: read_factory_settings would also disable the extension.
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add()
    a = bpy.context.object
    a.modifiers.new("Bevel", "BEVEL")
    for i in range(3):
        o = bpy.data.objects.new(f"copy{i}", a.data.copy())
        o.location = (3 * (i + 1), 0, 0)
        bpy.context.scene.collection.objects.link(o)
    check(bpy.ops.instance_checker.scan() == {"FINISHED"}, "scan")
    check(bpy.ops.instance_checker.instance_all() == {"FINISHED"}, "instance all")
    check(len({o.data.name for o in bpy.context.scene.objects}) == 1, "4 objects share one mesh")
    check([m.type for m in a.modifiers] == ["BEVEL"], "modifier kept")
    for o in bpy.context.scene.objects:
        o.select_set(True)
    check(bpy.ops.instance_checker.make_copies(target="SELECTED") == {"FINISHED"}, "make copies")
    check(len({o.data.name for o in bpy.context.scene.objects}) == 4, "4 meshes again")
    print("RESULT:", "PASS" if not fails else f"{len(fails)} FAILED")
    sys.exit(1 if fails else 0)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from run import find_blender, isolated_env

    args = sys.argv[1:]
    explicit = None
    if "--blender" in args:
        i = args.index("--blender")
        explicit = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    zip_path = os.path.abspath(args[0])
    blender = find_blender(explicit)
    with tempfile.TemporaryDirectory(prefix="ic_installed_") as profile:
        env = isolated_env(profile)
        subprocess.run([blender, "-b", "--factory-startup", "--command", "extension",
                        "install-file", "--repo", "user_default", "--enable", zip_path],
                       check=True, env=env)
        # No --factory-startup here: the scratch profile's preferences hold the enabled extension.
        return subprocess.call([blender, "-b", "--python-exit-code", "1",
                                "--python", os.path.abspath(__file__)], env=env)


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401  (only importable inside Blender)
    except ImportError:
        sys.exit(main())
    check_inside_blender()
