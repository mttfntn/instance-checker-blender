import bpy
import numpy as np
from bpy.props import EnumProperty, IntProperty
from mathutils import Matrix

from . import matching

# --------------------------------------------------------------------------
# Helpers (usable from scripts / Blender MCP as well)
# --------------------------------------------------------------------------


def settings(context):
    return context.scene.copy_instancer


def _scan_objects(context, s):
    if s.scope == "SELECTED":
        return list(context.selected_objects)
    return list(context.scene.objects)


def store_result(s, result):
    """Copy a matching.ScanResult into the scene properties."""
    s.groups.clear()
    total = 0.0
    for g in result.groups:
        if g.status == "INSTANCED" and not s.show_instanced:
            continue
        item = s.groups.add()
        item.name = g.reference.name
        item.reference_name = g.reference.name
        item.unique_meshes = g.unique_meshes
        item.verts = len(g.reference.vertices)
        item.faces = len(g.reference.polygons)
        item.mesh_bytes = matching.mesh_bytes(g.reference)
        item.saved_bytes = matching.group_savings(g)
        item.status = g.status
        item.transformed = sum(1 for m in g.members if m.needs_transform)
        total += item.saved_bytes
        for m in g.members:
            mi = item.members.add()
            mi.obj_name = m.obj.name
            mi.mesh_name = m.mesh.name
            mi.matrix = [float(v) for v in m.matrix.flatten()]
            mi.needs_transform = m.needs_transform
    s.skipped = len(result.skipped)
    s.total_saved = total
    s.active_index = min(s.active_index, max(len(s.groups) - 1, 0))


def scan(context, objects=None):
    s = settings(context)
    if objects is None:
        objects = _scan_objects(context, s)
    result = matching.find_groups(objects, tol=s.tolerance,
                                  allow_transform=s.match_transforms)
    store_result(s, result)
    return result


def _listed_objects(s):
    objs = {}
    for g in s.groups:
        for m in g.members:
            if m.obj is not None:
                objs[m.obj.name] = m.obj
    return list(objs.values())


def _eval_world_co(obj, depsgraph):
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
    finally:
        ev.to_mesh_clear()
    co = co.reshape(-1, 3).astype(np.float64)
    mw = np.array(ev.matrix_world)
    return co @ mw[:3, :3].T + mw[:3, 3]


def _same_result(a, b, tol):
    if a.shape != b.shape:
        return False
    if a.size == 0:
        return True
    extent = float(np.max(np.abs(a)))
    return float(np.max(np.abs(a - b))) <= max(tol * 10.0, extent * 1e-5)


def _has_transform_drivers(obj):
    if len(obj.constraints):
        return True
    ad = obj.animation_data
    return bool(ad and (ad.action or ad.drivers))


def instance_group(context, group, verify=True, tol=1e-4, remove_orphans=True):
    """Make every member of a stored group use the group's reference mesh.

    Returns (instanced_objects, [(object, reason), ...] not instanced).
    Modifiers live on the object, so they are kept as they are.
    """
    ref = group.reference
    failed = []
    changed = []  # (obj, backup)
    if ref is None:
        return [], [(None, "reference mesh was deleted")]

    view_layer = context.view_layer
    depsgraph = context.evaluated_depsgraph_get()

    todo = []
    for m in group.members:
        obj = m.obj
        if obj is None:
            failed.append((None, f"'{m.obj_name}' was renamed or deleted since the scan"))
            continue
        if obj.data == ref:
            continue
        if obj.data != m.mesh:
            failed.append((obj, "mesh changed since scan, rescan first"))
            continue
        if m.needs_transform and _has_transform_drivers(obj):
            failed.append((obj, "applied transform but object is animated/constrained"))
            continue
        # Blender doesn't evaluate objects in excluded collections, so their
        # modifier result can't be checked after the transform is compensated.
        if (verify and m.needs_transform and len(obj.modifiers)
                and not obj.evaluated_get(depsgraph).is_evaluated):
            failed.append((obj, "applied transform and modifiers, but not evaluated "
                                "(excluded collection?): can't verify, kept as copy"))
            continue
        todo.append(m)

    before = {}
    if verify:
        for m in todo:
            before[m.obj.name] = _eval_world_co(m.obj, depsgraph)

    # Swap the mesh data
    for m in todo:
        obj = m.obj
        backup = {
            "mesh": obj.data,
            "matrix": obj.matrix_world.copy(),
            "children": [(c, c.matrix_world.copy()) for c in obj.children],
            "slots": [(sl.link, sl.material) for sl in obj.material_slots],
            "changed_slots": [],
        }
        obj.data = ref
        if m.needs_transform:
            T = Matrix([m.matrix[i * 4:(i + 1) * 4] for i in range(4)])
            obj.matrix_world = backup["matrix"] @ T
        # Keep each object's own materials
        for i, sl in enumerate(obj.material_slots):
            if i >= len(backup["slots"]):
                break
            old_mat = backup["slots"][i][1]
            if sl.material != old_mat:
                sl.link = "OBJECT"
                sl.material = old_mat
                backup["changed_slots"].append(i)
        changed.append((obj, backup))

    view_layer.update()
    # Children must not move when the parent's transform was compensated
    for obj, backup in changed:
        if obj.matrix_world != backup["matrix"]:
            for child, mw in backup["children"]:
                child.matrix_world = mw
    view_layer.update()

    def revert(obj, backup):
        for i in backup["changed_slots"]:
            sl = obj.material_slots[i]
            sl.material = None
            sl.link = "DATA"
        obj.data = backup["mesh"]
        obj.matrix_world = backup["matrix"]
        for i, (link, _mat) in enumerate(backup["slots"]):
            if i < len(obj.material_slots):
                obj.material_slots[i].link = link
        view_layer.update()
        for child, mw in backup["children"]:
            child.matrix_world = mw

    ok = []
    if verify and changed:
        depsgraph = context.evaluated_depsgraph_get()
        depsgraph.update()
        reverted = False
        for obj, backup in changed:
            after = _eval_world_co(obj, depsgraph)
            if _same_result(before[obj.name], after, tol):
                ok.append((obj, backup))
            else:
                revert(obj, backup)
                reverted = True
                failed.append((obj, "result changed after instancing (modifiers depend on "
                                    "the applied transform), kept as copy"))
        if reverted:
            view_layer.update()
    else:
        ok = changed

    if remove_orphans:
        seen = set()
        for _obj, backup in ok:
            mesh = backup["mesh"]
            key = mesh.as_pointer()
            if key in seen:
                continue
            seen.add(key)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    return [o for o, _b in ok], failed


def make_copies(objects):
    """Give each object its own mesh copy (modifiers and materials are kept)."""
    by_mesh = {}
    for o in objects:
        if o.type == "MESH" and o.data is not None and o.library is None:
            by_mesh.setdefault(o.data.as_pointer(), []).append(o)
    count = 0
    for objs in by_mesh.values():
        mesh = objs[0].data
        # If every user of the mesh is a target, the first one keeps the original
        if mesh.users - (1 if mesh.use_fake_user else 0) <= len(objs):
            objs = objs[1:]
        for obj in objs:
            obj.data = mesh.copy()
            count += 1
    return count


# --------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------


class CI_OT_scan(bpy.types.Operator):
    bl_idname = "copy_instancer.scan"
    bl_label = "Scan for Copies"
    bl_description = "Find mesh objects that share the same topology and shape"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = settings(context)
        result = scan(context)
        copies = sum(1 for g in s.groups if g.status != "INSTANCED")
        msg = (f"{len(s.groups)} groups ({copies} with copies), "
               f"potential saving {matching.format_bytes(s.total_saved)}")
        if result.skipped:
            msg += f", {len(result.skipped)} skipped"
        s.last_message = msg
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class _GroupIndexMixin:
    index: IntProperty(default=-1, options={"SKIP_SAVE"})

    def _group(self, context):
        s = settings(context)
        idx = s.active_index if self.index < 0 else self.index
        if 0 <= idx < len(s.groups):
            return s.groups[idx]
        return None


class CI_OT_select_group(_GroupIndexMixin, bpy.types.Operator):
    bl_idname = "copy_instancer.select_group"
    bl_label = "Select Group"
    bl_description = "Select all objects of the group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        g = self._group(context)
        if g is None:
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        first = None
        for m in g.members:
            if m.obj and m.obj.name in context.view_layer.objects:
                m.obj.select_set(True)
                first = first or m.obj
        if first:
            context.view_layer.objects.active = first
        return {"FINISHED"}


def _report_failures(op, failed):
    for obj, reason in failed[:10]:
        op.report({"WARNING"}, f"{obj.name}: {reason}" if obj else reason)
    if len(failed) > 10:
        op.report({"WARNING"}, f"... and {len(failed) - 10} more")


class CI_OT_instance_group(_GroupIndexMixin, bpy.types.Operator):
    bl_idname = "copy_instancer.instance_group"
    bl_label = "Instance Group"
    bl_description = ("Make all objects of the group share one mesh (linked data). "
                      "Modifiers, materials and transforms are kept")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = settings(context)
        g = self._group(context)
        if g is None:
            return {"CANCELLED"}
        objs = _listed_objects(s)
        done, failed = instance_group(context, g, s.verify, s.tolerance, s.remove_orphans)
        scan(context, objs)
        _report_failures(self, failed)
        s.last_message = f"Instanced {len(done)} objects, {len(failed)} kept as copies"
        self.report({"INFO"}, s.last_message)
        return {"FINISHED"}


class CI_OT_instance_all(bpy.types.Operator):
    bl_idname = "copy_instancer.instance_all"
    bl_label = "Instance All"
    bl_description = "Instance every group in the list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = settings(context)
        objs = _listed_objects(s)
        before = s.total_saved
        done, failed = [], []
        for g in s.groups:
            if g.status == "INSTANCED":
                continue
            d, f = instance_group(context, g, s.verify, s.tolerance, s.remove_orphans)
            done += d
            failed += f
        scan(context, objs)
        _report_failures(self, failed)
        s.last_message = (f"Instanced {len(done)} objects, saved ~"
                          f"{matching.format_bytes(before - s.total_saved)}, "
                          f"{len(failed)} kept as copies")
        self.report({"INFO"}, s.last_message)
        return {"FINISHED"}


class CI_OT_make_copies(_GroupIndexMixin, bpy.types.Operator):
    bl_idname = "copy_instancer.make_copies"
    bl_label = "Make Copies"
    bl_description = ("Give each object its own copy of the mesh (un-instance). "
                      "Modifiers and materials are kept")
    bl_options = {"REGISTER", "UNDO"}

    target: EnumProperty(
        name="Target",
        items=[("SELECTED", "Selected Objects", ""),
               ("GROUP", "Active Group", "")],
        default="SELECTED",
    )

    def execute(self, context):
        s = settings(context)
        if self.target == "GROUP":
            g = self._group(context)
            if g is None:
                return {"CANCELLED"}
            objs = [m.obj for m in g.members if m.obj]
        else:
            objs = list(context.selected_objects)
        listed = _listed_objects(s)
        n = make_copies(objs)
        if s.groups:
            scan(context, listed or None)
        s.last_message = f"Made {n} independent copies"
        self.report({"INFO"}, s.last_message)
        return {"FINISHED"}


class CI_OT_report(bpy.types.Operator):
    bl_idname = "copy_instancer.report"
    bl_label = "Print Report"
    bl_description = "Print a memory report of all groups to the system console"

    def execute(self, context):
        s = settings(context)
        lines = [f"{'Group':30} {'Objs':>5} {'Meshes':>6} {'Verts':>8} "
                 f"{'Faces':>8} {'Mesh size':>11} {'Saving':>11}  Status"]
        for g in s.groups:
            lines.append(
                f"{g.name[:30]:30} {len(g.members):5d} {g.unique_meshes:6d} {g.verts:8d} "
                f"{g.faces:8d} {matching.format_bytes(g.mesh_bytes):>11} "
                f"{matching.format_bytes(g.saved_bytes):>11}  {g.status}")
        lines.append(f"Total potential saving: {matching.format_bytes(s.total_saved)}")
        text = "\n".join(lines)
        print(text)
        self.report({"INFO"}, f"Report printed to console. Total saving "
                              f"{matching.format_bytes(s.total_saved)}")
        return {"FINISHED"}


classes = (CI_OT_scan, CI_OT_select_group, CI_OT_instance_group,
           CI_OT_instance_all, CI_OT_make_copies, CI_OT_report)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
