"""Copy Instancer: find duplicated meshes, turn them into linked instances and back."""

from . import operators, properties, ui

_modules = (properties, operators, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
