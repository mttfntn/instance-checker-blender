"""Instance Checker tests, run inside Blender 5.3.

Run with the isolated runner (never your real Blender profile):
    python tests/run.py

The add-on package is loaded from $IC_ADDON_PATH (set by run.py) by adding its
parent folder to sys.path. The package name is the folder name, so the same
suite also runs on the version before the rename (copy_instancer).

Each case builds its own scene from factory settings and prints "ok"/"FAIL"
lines; the script exits non-zero if any check fails.
"""

import importlib
import io
import math
import os
import sys
import traceback

import bpy
import numpy as np
from mathutils import Matrix

ADDON = os.environ.get("IC_ADDON_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance_checker")
PKG = os.path.basename(os.path.normpath(ADDON))
sys.path.insert(0, os.path.dirname(os.path.normpath(ADDON)))
addon = importlib.import_module(PKG)
operators = importlib.import_module(f"{PKG}.operators")
matching = importlib.import_module(f"{PKG}.matching")
addon.register()

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ops():
    """bpy.ops.<package name>"""
    return getattr(bpy.ops, PKG)


def settings():
    return getattr(bpy.context.scene, PKG)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def world_eval(obj):
    return operators._eval_world_co(obj, bpy.context.evaluated_depsgraph_get())


def same_geometry(a, b):
    return a.shape == b.shape and np.allclose(a, b, atol=1e-4)


def mat(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = color
    return m


def new_obj(name, mesh, location=(0, 0, 0)):
    o = bpy.data.objects.new(name, mesh)
    o.location = location
    bpy.context.scene.collection.objects.link(o)
    return o


def new_cube(name, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=location)
    o = bpy.context.object
    o.name = name
    return o


def group_names():
    return {frozenset(m.obj.name for m in g.members if m.obj) for g in settings().groups}


# --------------------------------------------------------------------------
# Main scenario: copies with different modifiers, materials, applied transforms
# --------------------------------------------------------------------------

def build_main_scene():
    sc = reset()
    base = new_cube("A")
    red, blue = mat("Red", (1, 0, 0, 1)), mat("Blue", (0, 0, 1, 1))
    base.data.materials.append(red)
    base.modifiers.new("Bevel", "BEVEL").width = 0.2
    base.data.uv_layers.new(name="UVMap")

    # Shift+D style copies with different modifiers / materials
    b = new_obj("B", base.data.copy(), (4, 0, 0))
    b.modifiers.new("Subsurf", "SUBSURF").levels = 2
    c = new_obj("C", base.data.copy(), (8, 0, 0))
    c.modifiers.new("Array", "ARRAY").count = 3
    c.data.materials[0] = blue  # mesh-level material differs

    # Copy with applied rotation/scale/location + a child
    d_mesh = base.data.copy()
    d_mesh.transform(Matrix.Translation((0.5, 0.2, 0.1)) @ Matrix.Rotation(math.radians(35), 4, "Z")
                     @ Matrix.Rotation(math.radians(20), 4, "X") @ Matrix.Scale(1.7, 4))
    d = new_obj("D", d_mesh, (0, 6, 0))
    d.rotation_euler = (0, 0, math.radians(10))
    new_obj("D_child", bpy.data.meshes.new("empty_child"), (1, 1, 1)).parent = d

    # Same topology, different shape
    e_mesh = base.data.copy()
    e_mesh.vertices[0].co.x += 0.5
    new_obj("E", e_mesh, (0, -6, 0))

    # F: rotated-applied copy of G with a Mirror modifier (must be reverted)
    g = new_cube("G")
    g.data.transform(Matrix.Translation((3, 0, 0)))
    g.location = (0, 12, 0)
    f_mesh = g.data.copy()
    f_mesh.transform(Matrix.Rotation(math.radians(30), 4, "Z"))
    new_obj("F", f_mesh, (0, 18, 0)).modifiers.new("Mirror", "MIRROR")

    # Already instanced pair
    bpy.ops.mesh.primitive_cylinder_add()
    bpy.context.object.name = "H"
    new_obj("I", bpy.context.object.data, (3, 3, 0))

    # Shape keys: skipped
    bpy.ops.mesh.primitive_uv_sphere_add()
    sk = bpy.context.object
    sk.name = "SK"
    sk.shape_key_add(name="Basis")
    new_obj("SK2", sk.data.copy())

    bpy.context.view_layer.update()
    return sc


def test_main_scenario():
    build_main_scene()
    s = settings()
    names = ["A", "B", "C", "D", "E", "F", "G"]
    ob = bpy.data.objects
    before = {n: world_eval(ob[n]) for n in names}
    mods_before = {n: [m.name for m in ob[n].modifiers] for n in names}
    child_before = ob["D_child"].matrix_world.copy()
    mat_before = {n: [sl.material for sl in ob[n].material_slots] for n in names}

    print("\n== scan")
    ops().scan()
    print(" ", s.last_message)
    groups = {frozenset(m.obj.name for m in g.members): g for g in s.groups}
    check(frozenset({"A", "B", "C", "D"}) in groups, "A,B,C,D grouped (incl. applied transform D)")
    check(frozenset({"F", "G"}) in groups, "F,G grouped")
    check(not any("E" in k for k in groups), "E (moved vertex) not grouped")
    check(frozenset({"H", "I"}) in groups and groups[frozenset({"H", "I"})].status == "INSTANCED",
          "H,I reported as already instanced")
    check(s.skipped == 2, f"shape-key objects skipped ({s.skipped})")
    check(s.total_saved > 0, "positive potential saving")
    check(ops().report() == {"FINISHED"}, "report runs")

    print("\n== instance all")
    ops().instance_all()
    print(" ", s.last_message)
    bpy.context.view_layer.update()
    check(ob["A"].data == ob["B"].data == ob["C"].data == ob["D"].data, "A,B,C,D share one mesh")
    check(ob["E"].data != ob["A"].data, "E still unique")
    for n in names:
        check([m.name for m in ob[n].modifiers] == mods_before[n], f"{n} modifiers kept")
        check([sl.material for sl in ob[n].material_slots] == mat_before[n], f"{n} materials kept")
        check(same_geometry(before[n], world_eval(ob[n])), f"{n} evaluated world geometry unchanged")
    check(np.allclose(np.array(child_before), np.array(ob["D_child"].matrix_world), atol=1e-5),
          "D's child did not move")
    check(ob["F"].data != ob["G"].data, "F (mirror depends on applied rotation) reverted to copy")

    print("\n== make copies")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for n in ("A", "B", "C"):
        ob[n].select_set(True)
    ops().make_copies(target="SELECTED")
    meshes = {ob[n].data.name for n in ("A", "B", "C", "D")}
    check(len(meshes) == 4, f"A,B,C,D now have unique meshes ({sorted(meshes)})")
    for n in ("A", "B", "C", "D"):
        check([m.name for m in ob[n].modifiers] == mods_before[n], f"{n} modifiers kept after copy")
        check(same_geometry(before[n], world_eval(ob[n])), f"{n} geometry unchanged after copy")

    print("\n== re-instance")
    ops().scan()
    n_meshes = len(bpy.data.meshes)
    ops().instance_all()
    check(ob["A"].data == ob["B"].data, "re-instanced after making copies")
    check(len(bpy.data.meshes) == n_meshes - 3,
          f"replaced meshes removed ({n_meshes} -> {len(bpy.data.meshes)})")
    check(ob["A"].data.users == 4, f"no extra users held by the scan list ({ob['A'].data.users})")

    print("\n== make copies on a whole group keeps the original on one object")
    idx = next(i for i, g in enumerate(s.groups) if g.reference == ob["A"].data)
    shared = ob["A"].data
    ops().make_copies(target="GROUP", index=idx)
    check(s.last_message == "Made 3 independent copies", s.last_message)
    check(sum(1 for n in ("A", "B", "C", "D") if ob[n].data == shared) == 1,
          "exactly one object keeps the original mesh")


# --------------------------------------------------------------------------
# What counts as a copy
# --------------------------------------------------------------------------

def test_matching_rules():
    print("\n== matching rules")
    reset()
    bpy.ops.mesh.primitive_monkey_add()
    mk = bpy.context.object
    mk.name = "Monkey"
    mirrored = mk.data.copy()
    mirrored.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    new_obj("Mirrored", mirrored, (3, 0, 0))
    ops().scan()
    check(not any("Mirrored" in k for k in group_names()), "mirrored copy is not a copy")

    reset()
    a = new_cube("A")
    a.data.uv_layers.new(name="UVMap")
    b = new_obj("B", a.data.copy(), (3, 0, 0))
    c = new_obj("C", a.data.copy(), (6, 0, 0))
    c.data.uv_layers[0].uv[0].vector = (0.9, 0.9)
    b.data.vertices[0].select = not b.data.vertices[0].select  # editor-only difference
    ops().scan()
    gn = group_names()
    check(frozenset({"A", "B"}) in gn, "selection-only difference still a copy")
    check(not any("C" in k for k in gn), "different UVs are not a copy")

    reset()
    a = new_cube("A")
    vg = a.vertex_groups.new(name="w")
    vg.add([0, 1, 2], 0.5, "REPLACE")
    b = new_obj("B", a.data.copy(), (3, 0, 0))
    b.vertex_groups.new(name="w")
    c = new_obj("C", a.data.copy(), (6, 0, 0))
    c.vertex_groups.new(name="w").add([0], 0.25, "REPLACE")  # different weight on vertex 0
    ops().scan()
    gn = group_names()
    check(frozenset({"A", "B"}) in gn, "same vertex-group weights: a copy")
    check(not any("C" in k for k in gn), "different vertex-group weights: not a copy")

    reset()
    m = bpy.data.meshes.new("point")
    m.from_pydata([(0, 0, 0)], [], [])
    new_obj("P1", m)
    new_obj("P2", m.copy(), (1, 0, 0))
    m = bpy.data.meshes.new("line")
    m.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1), (1, 2)], [])
    new_obj("L1", m)
    m2 = m.copy()
    m2.transform(Matrix.Rotation(1.0, 4, "Z"))
    new_obj("L2", m2, (0, 3, 0))
    bpy.ops.object.empty_add()
    bpy.ops.object.text_add()
    ops().scan()
    ops().instance_all()
    ob = bpy.data.objects
    check(ob["P1"].data == ob["P2"].data, "single-vertex meshes instanced")
    check(ob["L1"].data == ob["L2"].data, "faceless rotated-applied lines instanced")


# --------------------------------------------------------------------------
# Regression checks for bugs fixed during the 1.0.0 cleanup
# --------------------------------------------------------------------------

def test_float4_size():
    print("\n== memory estimate counts FLOAT4 as 16 bytes")
    reset()
    a = new_cube("A")
    before = matching.mesh_bytes(a.data)
    a.data.attributes.new("f4", "FLOAT4", "POINT")
    added = matching.mesh_bytes(a.data) - before
    check(added == 8 * 16, f"FLOAT4 on 8 vertices adds 128 bytes (got {added})")


def test_tolerance_cap():
    print("\n== tolerance can't be raised past 0.01")
    reset()
    a = new_cube("A")
    m = a.data.copy()
    m.vertices[0].co.x += 0.5
    b = new_obj("B", m, (3, 0, 0))
    settings().tolerance = 1.0
    check(settings().tolerance <= 0.01 + 1e-9, f"tolerance clamped ({settings().tolerance})")
    before = world_eval(b)
    ops().scan()
    ops().instance_all()
    check(a.data != b.data, "a shape 0.5 away is not instanced")
    check(same_geometry(before, world_eval(b)), "nothing moved")


def test_renamed_or_deleted_reported():
    print("\n== objects renamed or deleted after the scan are reported")
    reset()
    a = new_cube("A")
    b = new_obj("B", a.data.copy(), (3, 0, 0))
    c = new_obj("C", a.data.copy(), (6, 0, 0))
    ops().scan()
    b.name = "B_renamed"
    bpy.data.objects.remove(c)
    ops().instance_group(index=0)
    msg = settings().last_message
    check(msg.endswith("2 kept as copies"), f"both reported ({msg!r})")


def test_excluded_collection():
    print("\n== unevaluated objects with modifiers and an applied transform stay copies")
    sc = reset()
    g = new_cube("G")
    g.data.transform(Matrix.Translation((3, 0, 0)))
    col = bpy.data.collections.new("Excluded")
    sc.collection.children.link(col)
    m = g.data.copy()
    m.transform(Matrix.Rotation(math.radians(30), 4, "Z"))
    f = bpy.data.objects.new("F", m)
    col.objects.link(f)
    f.modifiers.new("Mirror", "MIRROR")
    plain = bpy.data.objects.new("Plain", g.data.copy())
    col.objects.link(plain)
    before = world_eval(f)
    layer = bpy.context.view_layer.layer_collection.children["Excluded"]
    layer.exclude = True
    ops().scan()
    ops().instance_all()
    layer.exclude = False
    bpy.context.view_layer.update()
    check(f.data != g.data, "F kept as copy")
    check(same_geometry(before, world_eval(f)), "F's final shape unchanged")
    check(plain.data == g.data, "plain copy in the excluded collection still instanced")


def test_report_on_limited_console():
    print("\n== Print Report survives a console that can't show every character")
    reset()
    a = new_cube("A")
    a.data.name = "名前 mesh"
    new_obj("B", a.data.copy(), (3, 0, 0))
    ops().scan()
    real = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")  # redirected Windows console
    try:
        result = ops().report()
    except Exception as e:  # the operator error surfaces as RuntimeError
        result = f"{type(e).__name__}"
    finally:
        sys.stdout.flush()
        sys.stdout.detach()
        sys.stdout = real
    check(result == {"FINISHED"}, f"report finished on cp1252 ({result})")


def test_odd_input():
    print("\n== odd names, hidden objects, empty scene, bad indexes")
    sc = reset()
    a = new_cube("A")
    for i, n in enumerate(["ünïcödé 名前 🙂", "with.dots.001", "x" * 63, "  spaces  ", "%s{}\\/\"'"]):
        new_obj(n, a.data.copy(), (i + 2, 0, 0))
    hidden = new_obj("Hidden", a.data.copy(), (0, 3, 0))
    hidden.hide_viewport = True
    ops().scan()
    ops().instance_all()
    check(len({o.data.name for o in sc.objects}) == 1, "7 copies with odd names and a hidden one share one mesh")

    reset()
    results = [ops().scan(), ops().instance_all(), ops().instance_group(),
               ops().make_copies(target="GROUP"), ops().select_group(index=99)]
    check(results == [{"FINISHED"}, {"FINISHED"}, {"CANCELLED"}, {"CANCELLED"}, {"CANCELLED"}],
          f"empty scene and bad index don't raise ({results})")


def main():
    for case in (test_main_scenario, test_matching_rules, test_float4_size, test_tolerance_cap,
                 test_renamed_or_deleted_reported, test_excluded_collection,
                 test_report_on_limited_console, test_odd_input):
        try:
            case()
        except Exception:
            traceback.print_exc()
            check(False, f"{case.__name__} raised")
    print(f"\nRESULT: {'PASS' if not FAILS else f'{len(FAILS)} FAILED'} ({PKG})")
    return 1 if FAILS else 0


sys.exit(main())
