"""Instance Checker: find mesh copies, turn them into linked instances and back.

Modules, registered in this order:
  properties.py  scene settings and the stored scan list (scene.instance_checker)
  operators.py   scan, instance, make copies, report (bpy.ops.instance_checker.*)
  ui.py          the 3D Viewport sidebar panel (N > Instances)
matching.py holds the copy detection and is used by operators.py only.
"""

from . import operators, properties, ui

_modules = (properties, operators, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
