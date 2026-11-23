import bpy

from .matching import format_bytes

_STATUS_ICON = {"COPIES": "DUPLICATE", "PARTIAL": "MOD_INSTANCE", "INSTANCED": "LINKED"}


class IC_UL_groups(bpy.types.UIList):
    bl_idname = "IC_UL_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon=_STATUS_ICON.get(item.status, "MESH_DATA"))
        sub = row.row(align=True)
        sub.alignment = "RIGHT"
        sub.label(text=f"{len(item.members)} obj / {item.unique_meshes} mesh")
        if item.saved_bytes > 0:
            sub.label(text=format_bytes(item.saved_bytes))


class IC_PT_panel(bpy.types.Panel):
    bl_idname = "IC_PT_panel"
    bl_label = "Instance Checker"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Instances"

    def draw(self, context):
        s = context.scene.instance_checker
        layout = self.layout

        col = layout.column(align=True)
        col.row(align=True).prop(s, "scope", expand=True)
        col.operator("instance_checker.scan", icon="VIEWZOOM")

        box = layout.box()
        box.prop(s, "tolerance")
        box.prop(s, "match_transforms")
        box.prop(s, "show_instanced")
        box.prop(s, "verify")
        box.prop(s, "remove_orphans")

        if not s.groups:
            if s.last_message:
                layout.label(text=s.last_message)
            return

        layout.template_list("IC_UL_groups", "", s, "groups", s, "active_index", rows=6)

        row = layout.row(align=True)
        row.operator("instance_checker.select_group", icon="RESTRICT_SELECT_OFF")
        op = row.operator("instance_checker.make_copies", text="Make Copies", icon="DUPLICATE")
        op.target = "GROUP"
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("instance_checker.instance_group", icon="LINKED")
        row.operator("instance_checker.instance_all", icon="MOD_INSTANCE")
        layout.operator("instance_checker.make_copies", text="Make Selected Unique",
                        icon="UNLINKED").target = "SELECTED"

        # Optimization report
        box = layout.box()
        box.label(text="Memory Report", icon="MEMORY")
        if 0 <= s.active_index < len(s.groups):
            g = s.groups[s.active_index]
            c = box.column(align=True)
            c.label(text=f"Mesh: {g.reference.name if g.reference else '?'}")
            c.label(text=f"Objects: {len(g.members)}   Unique meshes: {g.unique_meshes}")
            c.label(text=f"Verts: {g.verts:,}   Faces: {g.faces:,}")
            c.label(text=f"Mesh size: {format_bytes(g.mesh_bytes)}")
            c.label(text=f"Saving: {format_bytes(g.saved_bytes)} "
                         f"({(g.unique_meshes - 1) * g.verts:,} verts)")
            if g.transformed:
                c.label(text=f"{g.transformed} with applied transforms", icon="ORIENTATION_GIMBAL")
        box.separator()
        box.label(text=f"Total potential saving: {format_bytes(s.total_saved)}")
        if s.skipped:
            box.label(text=f"{s.skipped} objects skipped (shape keys / linked)", icon="INFO")
        box.operator("instance_checker.report", icon="TEXT")
        if s.last_message:
            layout.label(text=s.last_message)


classes = (IC_UL_groups, IC_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
