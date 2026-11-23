"""Headless test for Copy Instancer.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/test_headless.py
"""
import math
import os
import sys
import traceback

import bpy
import numpy as np
from mathutils import Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import copy_instancer  # noqa: E402
from copy_instancer import operators  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def world_eval(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    return operators._eval_world_co(obj, dg)


def mat(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = color
    return m


def new_obj(name, mesh, location=(0, 0, 0)):
    o = bpy.data.objects.new(name, mesh)
    o.location = location
    bpy.context.scene.collection.objects.link(o)
    return o


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    copy_instancer.register()
    sc = bpy.context.scene

    bpy.ops.mesh.primitive_cube_add()
    base = bpy.context.object
    base.name = "A"
    red, blue = mat("Red", (1, 0, 0, 1)), mat("Blue", (0, 0, 1, 1))
    base.data.materials.append(red)
    base.modifiers.new("Bevel", "BEVEL").width = 0.2
    base.data.uv_layers.new(name="UVMap")

    # Shift+D style copies with different modifiers / materials
    b = new_obj("B", base.data.copy(), (4, 0, 0))
    b.modifiers.new("Subsurf", "SUBSURF").levels = 2
    c = new_obj("C", base.data.copy(), (8, 0, 0))
    arr = c.modifiers.new("Array", "ARRAY")
    arr.count = 3
    c.data.materials[0] = blue  # mesh-level material differs

    # Copy with applied rotation/scale/location + a child
    d_mesh = base.data.copy()
    T = Matrix.Translation((0.5, 0.2, 0.1)) @ Matrix.Rotation(math.radians(35), 4, "Z") \
        @ Matrix.Rotation(math.radians(20), 4, "X") @ Matrix.Scale(1.7, 4)
    d_mesh.transform(T)
    d = new_obj("D", d_mesh, (0, 6, 0))
    d.rotation_euler = (0, 0, math.radians(10))
    child = new_obj("D_child", bpy.data.meshes.new("empty_child"), (1, 1, 1))
    child.parent = d

    # Same topology, different shape
    e_mesh = base.data.copy()
    e_mesh.vertices[0].co.x += 0.5
    new_obj("E", e_mesh, (0, -6, 0))

    # Offset cube; F is a rotated-applied copy with a mirror modifier (must be reverted)
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    g = bpy.context.object
    g.name = "G"
    g.data.transform(Matrix.Translation((3, 0, 0)))
    g.location = (0, 12, 0)
    f_mesh = g.data.copy()
    f_mesh.transform(Matrix.Rotation(math.radians(30), 4, "Z"))
    f = new_obj("F", f_mesh, (0, 18, 0))
    f.modifiers.new("Mirror", "MIRROR")

    # Already instanced pair
    bpy.ops.mesh.primitive_cylinder_add()
    h = bpy.context.object
    h.name = "H"
    new_obj("I", h.data, (3, 3, 0))

    # Shape keys: skipped
    bpy.ops.mesh.primitive_uv_sphere_add()
    sk = bpy.context.object
    sk.name = "SK"
    sk.shape_key_add(name="Basis")
    new_obj("SK2", sk.data.copy())

    bpy.context.view_layer.update()
    return sc


def main():
    sc = build_scene()
    s = sc.copy_instancer
    names = ["A", "B", "C", "D", "E", "F", "G"]
    ob = bpy.data.objects
    before = {n: world_eval(ob[n]) for n in names}
    mods_before = {n: [m.name for m in ob[n].modifiers] for n in names}
    child_before = ob["D_child"].matrix_world.copy()
    mat_before = {n: [sl.material for sl in ob[n].material_slots] for n in names}

    print("\n== scan")
    bpy.ops.copy_instancer.scan()
    print(" ", s.last_message)
    groups = {frozenset(m.obj.name for m in g.members): g for g in s.groups}
    for k, g in groups.items():
        print("   group", sorted(k), g.status, g.unique_meshes, "saving", g.saved_bytes)
    check(frozenset({"A", "B", "C", "D"}) in groups, "A,B,C,D grouped (incl. applied transform D)")
    check(frozenset({"F", "G"}) in groups, "F,G grouped")
    check(not any("E" in k for k in groups), "E (moved vertex) not grouped")
    check(frozenset({"H", "I"}) in groups and groups[frozenset({"H", "I"})].status == "INSTANCED",
          "H,I reported as already instanced")
    check(s.skipped == 2, f"shape-key objects skipped ({s.skipped})")
    check(s.total_saved > 0, "positive potential saving")

    bpy.ops.copy_instancer.report()

    print("\n== instance all")
    bpy.ops.copy_instancer.instance_all()
    print(" ", s.last_message)
    bpy.context.view_layer.update()
    check(ob["A"].data == ob["B"].data == ob["C"].data == ob["D"].data, "A,B,C,D share one mesh")
    check(ob["E"].data != ob["A"].data, "E still unique")
    for n in names:
        check([m.name for m in ob[n].modifiers] == mods_before[n], f"{n} modifiers kept")
        check([sl.material for sl in ob[n].material_slots] == mat_before[n], f"{n} materials kept")
        after = world_eval(ob[n])
        same = before[n].shape == after.shape and np.allclose(before[n], after, atol=1e-4)
        check(same, f"{n} evaluated world geometry unchanged")
    check(np.allclose(np.array(child_before), np.array(ob["D_child"].matrix_world), atol=1e-5),
          "D's child did not move")
    check(ob["F"].data != ob["G"].data, "F (mirror depends on applied rotation) reverted to copy")

    print("\n== make copies")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for n in ("A", "B", "C"):
        ob[n].select_set(True)
    bpy.ops.copy_instancer.make_copies(target="SELECTED")
    meshes = {ob[n].data.name for n in ("A", "B", "C", "D")}
    check(len(meshes) == 4, f"A,B,C,D now have unique meshes ({meshes})")
    for n in ("A", "B", "C", "D"):
        check([m.name for m in ob[n].modifiers] == mods_before[n], f"{n} modifiers kept after copy")
        after = world_eval(ob[n])
        check(np.allclose(before[n], after, atol=1e-4), f"{n} geometry unchanged after copy")

    print("\n== undo-safe re-instance")
    bpy.ops.copy_instancer.scan()
    n_meshes = len(bpy.data.meshes)
    bpy.ops.copy_instancer.instance_all()
    check(ob["A"].data == ob["B"].data, "re-instanced after making copies")
    check(len(bpy.data.meshes) == n_meshes - 3,
          f"replaced meshes removed ({n_meshes} -> {len(bpy.data.meshes)})")
    check(ob["A"].data.users == 4, f"no extra users held by the scan list ({ob['A'].data.users})")

    print("\n== make copies on a whole group keeps the original on one object")
    idx = next(i for i, g in enumerate(s.groups) if g.reference == ob["A"].data)
    shared = ob["A"].data
    bpy.ops.copy_instancer.make_copies(target="GROUP", index=idx)
    check(s.last_message == "Made 3 independent copies", s.last_message)
    check(sum(1 for n in ("A", "B", "C", "D") if ob[n].data == shared) == 1,
          "exactly one object keeps the original mesh")

    print("\nRESULT:", "PASS" if not FAILS else f"{len(FAILS)} FAILED")
    return 0 if not FAILS else 1


try:
    code = main()
except Exception:
    traceback.print_exc()
    code = 2
sys.exit(code)
