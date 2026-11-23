import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)


# Objects and meshes are stored by name, not as ID pointers: pointers would
# count as extra users and keep replaced meshes alive / confuse user counts.


def _local(collection, name):
    item = collection.get((name, None)) if name else None
    return item if item is not None else (collection.get(name) if name else None)


class CI_Member(bpy.types.PropertyGroup):
    obj_name: StringProperty()
    mesh_name: StringProperty()

    @property
    def obj(self):
        return _local(bpy.data.objects, self.obj_name)

    @property
    def mesh(self):
        return _local(bpy.data.meshes, self.mesh_name)

    # ref-local -> member-local, row-major 4x4
    matrix: FloatVectorProperty(size=16)
    needs_transform: BoolProperty()


class CI_Group(bpy.types.PropertyGroup):
    reference_name: StringProperty()

    @property
    def reference(self):
        return _local(bpy.data.meshes, self.reference_name)

    members: CollectionProperty(type=CI_Member)
    unique_meshes: IntProperty()
    verts: IntProperty()
    faces: IntProperty()
    mesh_bytes: FloatProperty()
    saved_bytes: FloatProperty()
    status: EnumProperty(items=[
        ("COPIES", "Copies", "Every object has its own copy of the mesh", "DUPLICATE", 0),
        ("PARTIAL", "Partial", "Some objects already share the mesh", "MOD_INSTANCE", 1),
        ("INSTANCED", "Instanced", "All objects share one mesh", "LINKED", 2),
    ])
    transformed: IntProperty(description="Members that need a transform change")


class CI_Settings(bpy.types.PropertyGroup):
    scope: EnumProperty(
        name="Scope",
        items=[("SELECTED", "Selected", "Scan only selected objects"),
               ("SCENE", "Scene", "Scan every object in the scene")],
        default="SCENE",
    )
    tolerance: FloatProperty(
        name="Tolerance", default=1e-4, min=0.0, max=0.01,
        precision=6, step=0.001,
        description="Maximum vertex distance (local units) for two shapes to count as equal",
    )
    match_transforms: BoolProperty(
        name="Match Applied Transforms", default=True,
        description=("Also detect copies whose rotation/scale/location was applied to the mesh; "
                     "the object transform is adjusted so nothing moves"),
    )
    show_instanced: BoolProperty(
        name="Show Already Instanced", default=True,
        description="List groups that already share a single mesh",
    )
    verify: BoolProperty(
        name="Verify Result", default=True,
        description=("After instancing, compare the evaluated (modifiers applied) geometry with "
                     "the original and revert any object whose result changed"),
    )
    remove_orphans: BoolProperty(
        name="Remove Unused Meshes", default=True,
        description="Delete mesh data that has no users after instancing",
    )
    groups: CollectionProperty(type=CI_Group)
    active_index: IntProperty()
    skipped: IntProperty()
    total_saved: FloatProperty()
    last_message: StringProperty()


classes = (CI_Member, CI_Group, CI_Settings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.copy_instancer = PointerProperty(type=CI_Settings)


def unregister():
    del bpy.types.Scene.copy_instancer
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
