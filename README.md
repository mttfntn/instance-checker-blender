# Copy Instancer (Blender 4.2+ / 5.x extension)

Finds mesh objects that are copies of each other, converts them to **linked mesh data**
(Alt+D style instances) and back, and shows how much memory instancing saves.
Each object keeps its own **modifiers**, **materials** and **transform**.

## Install
1. Build the zip (or use `dist/copy_instancer-1.0.0.zip`):
   ```bash
   /Applications/Blender.app/Contents/MacOS/Blender --command extension build --source-dir copy_instancer --output-dir dist
   ```
2. Blender → Edit → Preferences → Get Extensions → ⌄ menu → *Install from Disk…* → pick the zip.
3. 3D Viewport → sidebar (N) → **Instancer** tab.

## How copies are detected
- **Topology**: same vertices/edges/faces/corners in the same order (hashed, fast).
- **Shape**: local vertex positions equal within *Tolerance*. With *Match Applied Transforms*,
  copies whose rotation/scale/location were applied to the mesh are also found; the object's
  transform is adjusted when instancing so nothing moves.
- **Other data must match**: UVs, color attributes, creases, sharp flags, material indices,
  vertex-group weights, number of material slots.
- Skipped: meshes with shape keys, linked-library objects.

## Operations
| Button | What it does |
|---|---|
| Scan for Copies | Scan the scene or the selection, list groups |
| Select Group | Select every object of the active group |
| Instance Group / Instance All | Make members share one mesh. Modifiers stay on each object. If a copy had different mesh-level materials, its slots are switched to *Object* link so it keeps its look. |
| Make Copies | Give each object of the group its own mesh again |
| Make Selected Unique | Same, for the selected objects |
| Print Report | Memory table in the system console |

**Verify Result** (on by default) evaluates each object with its modifiers before and after
instancing and reverts any object whose final geometry changed — e.g. a Mirror modifier on a
copy whose rotation had been applied to the mesh.

## Memory report
Per group: objects, unique meshes, verts/faces, estimated mesh size and the saving
`(unique meshes − 1) × mesh size`. The panel shows the total potential saving.

## Scripting / Blender MCP
```python
import bpy
bpy.ops.copy_instancer.scan()
bpy.ops.copy_instancer.instance_all()
s = bpy.context.scene.copy_instancer
print(s.last_message, [(g.name, len(g.members), g.status) for g in s.groups])
```
`.mcp.json` registers the Blender MCP server for this project (the BlenderMCP addon must be
enabled and connected inside Blender).

## Tests
```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python tests/test_headless.py
```
