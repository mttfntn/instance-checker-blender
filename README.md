# Instance Checker

[![Blender](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmttfntn%2Finstance-checker-blender%2Fmain%2Finstance_checker%2Fblender_manifest.toml&query=%24.blender_version_min&label=Blender&color=E87D0D&logo=blender&logoColor=white)](https://www.blender.org/download/)
[![Release](https://img.shields.io/github/v/release/mttfntn/instance-checker-blender)](https://github.com/mttfntn/instance-checker-blender/releases/latest)
[![Tests](https://github.com/mttfntn/instance-checker-blender/actions/workflows/ci.yml/badge.svg)](https://github.com/mttfntn/instance-checker-blender/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/mttfntn/instance-checker-blender)](LICENSE)
[![Language](https://img.shields.io/github/languages/top/mttfntn/instance-checker-blender)](https://github.com/mttfntn/instance-checker-blender)

A Blender extension that finds mesh objects that are **copies of each other**,
turns them into **linked instances** (one shared mesh, like Alt+D) and back, and
shows how much memory instancing saves. Each object keeps its own **modifiers**,
**materials** and **transform**.

Supports **Blender 5.3** only.

## Install

1. Download `instance_checker-<version>.zip` from the
   [latest release](https://github.com/mttfntn/instance-checker-blender/releases/latest).
2. In Blender: **Edit › Preferences › Get Extensions**, then the **⌄** menu (top right)
   › **Install from Disk…**, and pick the zip.

## Use

Open the 3D Viewport sidebar (**N**) › **Instances** tab, choose **Scene** or
**Selected**, and press **Scan for Copies**.

| Control | What it does |
|---|---|
| **Scan for Copies** | Finds groups of copies and lists them, largest saving first. |
| List rows | Group name, objects / distinct meshes, and the memory instancing would save. The icon shows *Copies*, *Partial* (some already share) or *Instanced*. |
| **Select Group** | Selects every object of the active group. |
| **Instance Group** / **Instance All** | Makes the objects of the active group (or of every group) share one mesh. Undoable. |
| **Make Copies** | Gives the objects of the active group their own meshes again. |
| **Make Selected Unique** | Gives the selected objects their own meshes. |
| **Print Report** | Prints a table of all groups to the system console. |

When every object using a mesh gets its own copy, one of them keeps the original.

### Options

| Option | Default | What it does |
|---|---|---|
| **Tolerance** | 0.0001 | Largest difference allowed in any vertex coordinate (in the mesh's own units), and in UVs and other float data. At most 0.01. |
| **Match Applied Transforms** | on | Also finds copies whose rotation, uniform scale or location was applied to the mesh. When instanced, the object's transform is changed so it stays where it is (its children too). |
| **Show Already Instanced** | on | Also lists groups that already share one mesh. |
| **Verify Result** | on | After instancing, compares each object's final geometry (with modifiers) to before, and puts it back as a copy if a vertex moved by more than 10 × Tolerance (or float precision, for large objects). |
| **Remove Unused Meshes** | on | Deletes the meshes that were replaced, once nothing uses them. |

The **Memory Report** box shows the active group's mesh size, vertices, faces
and saving, and the total saving of the whole list.

### What counts as a copy

Two meshes are copies when they have the same vertices, edges and faces **in the
same order**, the same number of material slots, the same shape (directly, or
after a rotation, uniform scale and move), and the same UVs, colors, creases,
sharp edges, material indices and vertex-group weights. Selection and hidden
state don't matter. A copy with different materials on its mesh keeps them: its
material slots are switched to *Object* when it is instanced.

### Things it leaves alone (and reports)

- **Mirrored copies** (negative scale applied to the mesh) and copies with
  non-uniform scale applied: not detected.
- **Meshes with shape keys** and **objects linked from a library**: skipped.
- **Modifiers that depend on the applied transform** (for example a Mirror on a
  copy whose rotation was applied): *Verify Result* sees the change and keeps the
  object as a copy.
- Copies that need a transform change but are **animated or constrained**: kept
  as copies (the animation would undo the change).
- With *Verify Result* on, copies that need a transform change, have modifiers
  and sit in an **excluded collection**: kept as copies (Blender doesn't
  evaluate them, so they can't be checked).
- Objects **renamed or deleted** after the scan: reported; scan again.

## For developers

- [HANDOVER.md](HANDOVER.md): how the project is organized, tested and released.
- [AGENTS.md](AGENTS.md): the same, compact, for AI coding assistants.

Run the tests (needs Blender 5.3; uses a throwaway profile):

```
python tests/run.py
```

Scripting:

```python
import bpy
bpy.ops.instance_checker.scan()
bpy.ops.instance_checker.instance_all()
s = bpy.context.scene.instance_checker
print(s.last_message, [(g.name, len(g.members), g.status) for g in s.groups])
```

## License

[GPL-3.0-or-later](LICENSE). © 2026 Matteo Fontana.
