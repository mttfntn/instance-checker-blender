"""Compare the behaviour of two versions of the add-on on many generated scenes.

Usage (outside Blender):
    python tests/compare_behaviour.py OLD_PACKAGE_DIR [NEW_PACKAGE_DIR]

NEW_PACKAGE_DIR defaults to ./instance_checker. OLD_PACKAGE_DIR is usually the
package folder of a git worktree of an earlier commit, e.g.:
    git worktree add /tmp/ic_old v1.0.0
    python tests/compare_behaviour.py /tmp/ic_old/instance_checker

For every seed (random scene of copies, applied transforms, modifiers,
materials, UV and vertex-group differences) and every option combination it
records: the groups found, the scan numbers, which objects share a mesh after
Instance All, every object's evaluated geometry (rounded) and the messages,
then the same after Make Copies. Each version runs in its own isolated Blender
(tests/run.py). The script first runs NEW twice to show the output is
deterministic, then diffs OLD against NEW and prints every difference.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile

SEEDS = range(12)
OPTIONS = [  # tolerance, match_transforms, verify, show_instanced, scope
    (1e-4, True, True, True, "SCENE"),
    (1e-4, False, True, True, "SCENE"),
    (1e-4, True, False, True, "SCENE"),
    (0.0, True, True, False, "SCENE"),
    (0.01, True, True, True, "SCENE"),
    (1e-4, True, True, True, "SELECTED"),
]


# --------------------------------------------------------------------------
# Inside Blender
# --------------------------------------------------------------------------

def build_scene(seed):
    import bpy
    from mathutils import Matrix
    rnd = random.Random(seed)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    mats = [bpy.data.materials.new(f"M{i}") for i in range(3)]
    makers = [bpy.ops.mesh.primitive_cube_add, bpy.ops.mesh.primitive_monkey_add,
              bpy.ops.mesh.primitive_cylinder_add, bpy.ops.mesh.primitive_torus_add]
    for b in range(4):
        rnd.choice(makers)()
        base = bpy.context.object
        base.name = f"base{b}"
        base.data.materials.append(rnd.choice(mats))
        if rnd.random() < 0.5:
            base.data.uv_layers.new(name="UVMap")
        if rnd.random() < 0.3:
            base.vertex_groups.new(name="w").add([0, 1], 0.5, "REPLACE")
        for i in range(rnd.randint(1, 5)):
            kind = rnd.random()
            mesh = base.data if kind < 0.15 else base.data.copy()
            if mesh is not base.data:
                if kind < 0.45:
                    mesh.transform(Matrix.Rotation(rnd.uniform(-3, 3), 4, rnd.choice("XYZ"))
                                   @ Matrix.Scale(rnd.uniform(0.5, 2), 4))
                elif kind < 0.55:
                    mesh.vertices[0].co.x += rnd.choice([1e-6, 0.005, 0.5])
                elif kind < 0.62 and mesh.uv_layers:
                    mesh.uv_layers[0].uv[0].vector = (0.3, 0.7)
                elif kind < 0.7:
                    mesh.materials[0] = rnd.choice(mats)
            o = bpy.data.objects.new(f"b{b}_{i}", mesh)
            o.location = (b * 5, i * 3, 0)
            o.rotation_euler = (0, 0, rnd.uniform(-1, 1))
            sc.collection.objects.link(o)
            if base.vertex_groups:
                o.vertex_groups.new(name="w")
            mod = rnd.choice([None, "SUBSURF", "BEVEL", "MIRROR", "ARRAY", "SOLIDIFY"])
            if mod:
                o.modifiers.new(mod, mod)
            o.select_set(rnd.random() < 0.6)
    bpy.context.view_layer.update()


def fingerprint_state(pkg, operators):
    import bpy
    import numpy as np
    sc = bpy.context.scene
    s = getattr(sc, pkg)
    dg = bpy.context.evaluated_depsgraph_get()
    geo = {}
    for o in sorted(sc.objects, key=lambda o: o.name):
        co = np.round(operators._eval_world_co(o, dg), 3) + 0.0  # +0.0 folds -0.0
        geo[o.name] = hashlib.sha1(co.tobytes()).hexdigest()[:12]
    sharing = {}
    for o in sc.objects:
        sharing.setdefault(o.data.name, []).append(o.name)
    return {
        "groups": [[sorted(m.obj.name for m in g.members if m.obj), g.status, g.unique_meshes,
                    g.verts, g.faces, g.transformed, round(g.saved_bytes)] for g in s.groups],
        "shared": sorted(sorted(v) for v in sharing.values() if len(v) > 1),
        "geometry": geo,
        "message": s.last_message,
        "skipped": s.skipped,
    }


def run_in_blender(out_path):
    import importlib
    import bpy
    addon = os.environ["IC_ADDON_PATH"]
    pkg = os.path.basename(os.path.normpath(addon))
    sys.path.insert(0, os.path.dirname(os.path.normpath(addon)))
    importlib.import_module(pkg).register()
    operators = importlib.import_module(f"{pkg}.operators")
    ops = getattr(bpy.ops, pkg)
    results = {}
    for seed in SEEDS:
        for opt in OPTIONS:
            build_scene(seed)
            s = getattr(bpy.context.scene, pkg)
            s.tolerance, s.match_transforms, s.verify, s.show_instanced, s.scope = opt
            key = f"seed={seed} opts={opt}"
            ops.scan()
            r = {"scan": fingerprint_state(pkg, operators)}
            ops.instance_all()
            r["instance_all"] = fingerprint_state(pkg, operators)
            for o in bpy.context.scene.objects:
                o.select_set(o.name.endswith(("_0", "_1")))
            ops.make_copies(target="SELECTED")
            r["make_copies"] = fingerprint_state(pkg, operators)
            results[key] = r
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------
# Outside Blender
# --------------------------------------------------------------------------

def run_version(addon_dir, out_path):
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(here, "run.py"), "--addon", addon_dir,
           "--script", os.path.abspath(__file__), "--", out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not os.path.exists(out_path):
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        sys.exit(f"Blender run failed for {addon_dir}")
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def diff(a, b, path=""):
    """Yield (path, a, b) for every leaf that differs."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from diff(a.get(k), b.get(k), f"{path}/{k}")
    elif a != b:
        yield path, a, b


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    old_dir = os.path.abspath(sys.argv[1])
    new_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(root, "instance_checker")
    tmp = tempfile.mkdtemp(prefix="ic_compare_")
    new1 = run_version(new_dir, os.path.join(tmp, "new1.json"))
    new2 = run_version(new_dir, os.path.join(tmp, "new2.json"))
    noise = list(diff(new1, new2))
    print(f"{len(new1)} runs (seeds x option sets). NEW vs NEW: {len(noise)} differences")
    for d in noise[:20]:
        print("  ", d)
    old = run_version(old_dir, os.path.join(tmp, "old.json"))
    diffs = list(diff(old, new1))
    print(f"OLD vs NEW: {len(diffs)} differences")
    for p, a, b in diffs:
        print(f"  {p}\n     old: {a}\n     new: {b}")
    return 1 if noise else 0


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401  (only importable inside Blender)
    except ImportError:
        sys.exit(main())
    run_in_blender(sys.argv[sys.argv.index("--") + 1])
